//! The retrieval index (specification sections 3.3 and 7): reads a FAISS index file
//! and blends each feature frame with its nearest stored vectors.
//!
//! Two layouts are read: the inverted-file index with uncompressed vectors that voice
//! model training produces, and the plain flat index. Both keep every vector verbatim,
//! so the "feature array" the specification asks for is the stored data itself.

use std::path::Path;

use crate::error::{Error, Result};

const KIND: &str = "index";
/// Neighbours blended per frame.
pub const NEIGHBOURS: usize = 8;

/// A searchable set of feature vectors.
#[derive(Debug, Clone)]
pub struct FeatureIndex {
    dim: usize,
    /// Every stored vector, grouped by inverted list (a flat index is one list).
    vectors: Vec<f32>,
    /// Start of each list in `vectors`, in vectors; one more entry than there are lists.
    list_starts: Vec<usize>,
    /// Identifier of each stored vector, in storage order.
    ids: Vec<i64>,
    /// One centroid per list; empty for a flat index.
    centroids: Vec<f32>,
    /// How many of the closest lists a query scans.
    nprobe: usize,
}

/// One neighbour: the squared L2 distance the index reports and where the vector is.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Neighbour {
    pub distance: f32,
    pub id: i64,
    slot: usize,
}

struct Reader<'a> {
    bytes: &'a [u8],
    at: usize,
}

impl<'a> Reader<'a> {
    fn take(&mut self, count: usize) -> Result<&'a [u8]> {
        let end = self.at.checked_add(count).filter(|&end| end <= self.bytes.len()).ok_or_else(|| Error::format(KIND, "file is truncated"))?;
        let bytes = &self.bytes[self.at..end];
        self.at = end;
        Ok(bytes)
    }

    fn fourcc(&mut self) -> Result<[u8; 4]> {
        Ok(self.take(4)?.try_into().unwrap())
    }

    fn u8(&mut self) -> Result<u8> {
        Ok(self.take(1)?[0])
    }

    fn i32(&mut self) -> Result<i32> {
        Ok(i32::from_le_bytes(self.take(4)?.try_into().unwrap()))
    }

    fn u64(&mut self) -> Result<usize> {
        usize::try_from(u64::from_le_bytes(self.take(8)?.try_into().unwrap())).map_err(|_| Error::format(KIND, "size does not fit"))
    }

    fn f32s(&mut self, count: usize) -> Result<Vec<f32>> {
        let bytes = self.take(count.checked_mul(4).ok_or_else(|| Error::format(KIND, "size overflow"))?)?;
        Ok(bytes.chunks_exact(4).map(|chunk| f32::from_le_bytes(chunk.try_into().unwrap())).collect())
    }

    fn i64s(&mut self, count: usize) -> Result<Vec<i64>> {
        let bytes = self.take(count.checked_mul(8).ok_or_else(|| Error::format(KIND, "size overflow"))?)?;
        Ok(bytes.chunks_exact(8).map(|chunk| i64::from_le_bytes(chunk.try_into().unwrap())).collect())
    }

    /// The header every index starts with after its type tag: dimension and vector count.
    fn header(&mut self) -> Result<(usize, usize)> {
        let dim = usize::try_from(self.i32()?).ok().filter(|&dim| dim > 0).ok_or_else(|| Error::format(KIND, "bad dimension"))?;
        let total = self.u64()?;
        self.take(16)?; // two reserved fields
        self.u8()?; // is_trained
        let metric = self.i32()?;
        if metric != 1 {
            return Err(Error::unsupported(KIND, "only L2 indexes are supported"));
        }
        Ok((dim, total))
    }

    /// A flat index body: the vectors themselves.
    fn flat(&mut self) -> Result<(usize, Vec<f32>)> {
        let (dim, total) = self.header()?;
        let count = self.u64()?;
        if count != total.checked_mul(dim).ok_or_else(|| Error::format(KIND, "size overflow"))? {
            return Err(Error::format(KIND, "flat storage size disagrees with the header"));
        }
        Ok((dim, self.f32s(count)?))
    }
}

impl FeatureIndex {
    pub fn load(path: &Path) -> Result<Self> {
        Self::from_bytes(&std::fs::read(path)?)
    }

    pub fn from_bytes(bytes: &[u8]) -> Result<Self> {
        let mut reader = Reader { bytes, at: 0 };
        let index = match &reader.fourcc()? {
            b"IxF2" => {
                let (dim, vectors) = reader.flat()?;
                let total = vectors.len() / dim;
                FeatureIndex { dim, vectors, list_starts: vec![0, total], ids: (0..total as i64).collect(), centroids: Vec::new(), nprobe: 1 }
            }
            b"IwFl" => Self::inverted(&mut reader)?,
            other => return Err(Error::unsupported(KIND, format!("index type {:?}", String::from_utf8_lossy(other)))),
        };
        if index.ids.is_empty() {
            // A trained-but-empty index (the `trained_*.index` a training run leaves behind).
            return Err(Error::invalid("the index holds no vectors; use the `added_*.index` file"));
        }
        Ok(index)
    }

    fn inverted(reader: &mut Reader) -> Result<Self> {
        let (dim, total) = reader.header()?;
        let lists = reader.u64()?;
        let nprobe = reader.u64()?.max(1);
        if &reader.fourcc()? != b"IxF2" {
            return Err(Error::unsupported(KIND, "coarse quantizer is not a flat L2 index"));
        }
        let (centroid_dim, centroids) = reader.flat()?;
        if centroid_dim != dim || centroids.len() != lists * dim {
            return Err(Error::format(KIND, "centroids disagree with the header"));
        }
        // Direct map: a kind byte, an id array and, for the hash kind, a table.
        let kind = reader.u8()?;
        let entries = reader.u64()?;
        reader.take(entries.checked_mul(8).ok_or_else(|| Error::format(KIND, "size overflow"))?)?;
        if kind == 2 {
            let pairs = reader.u64()?;
            reader.take(pairs.checked_mul(16).ok_or_else(|| Error::format(KIND, "size overflow"))?)?;
        }
        if &reader.fourcc()? != b"ilar" {
            return Err(Error::unsupported(KIND, "inverted lists are not stored inline"));
        }
        let stored_lists = reader.u64()?;
        let code_size = reader.u64()?;
        if stored_lists != lists || code_size != dim * 4 {
            return Err(Error::format(KIND, "inverted lists disagree with the header"));
        }
        let mut sizes = vec![0usize; lists];
        match &reader.fourcc()? {
            b"full" => {
                if reader.u64()? != lists {
                    return Err(Error::format(KIND, "list size table has the wrong length"));
                }
                for size in sizes.iter_mut() {
                    *size = reader.u64()?;
                }
            }
            b"sprs" => {
                // Pairs of (list number, size) for the non-empty lists.
                let count = reader.u64()?;
                for _ in 0..count / 2 {
                    let (list, size) = (reader.u64()?, reader.u64()?);
                    *sizes.get_mut(list).ok_or_else(|| Error::format(KIND, "list number out of range"))? = size;
                }
            }
            _ => return Err(Error::format(KIND, "unknown list size encoding")),
        }
        if sizes.iter().try_fold(0usize, |sum, &size| sum.checked_add(size)) != Some(total) {
            return Err(Error::format(KIND, "list sizes do not add up to the vector count"));
        }
        let mut vectors = Vec::with_capacity(total * dim);
        let mut ids = Vec::with_capacity(total);
        let mut list_starts = Vec::with_capacity(lists + 1);
        for &size in &sizes {
            list_starts.push(ids.len());
            vectors.extend(reader.f32s(size * dim)?);
            ids.extend(reader.i64s(size)?);
        }
        list_starts.push(ids.len());
        Ok(FeatureIndex { dim, vectors, list_starts, ids, centroids, nprobe })
    }

    pub fn dim(&self) -> usize {
        self.dim
    }

    /// Number of stored vectors.
    pub fn len(&self) -> usize {
        self.ids.len()
    }

    pub fn is_empty(&self) -> bool {
        self.ids.is_empty()
    }

    fn vector(&self, slot: usize) -> &[f32] {
        &self.vectors[slot * self.dim..(slot + 1) * self.dim]
    }

    /// The `k` nearest stored vectors by squared L2 distance, closest first.
    ///
    /// With centroids present only the `nprobe` lists closest to the query are scanned,
    /// which is the approximate search the index was built for; fewer than `k` results
    /// come back when those lists hold fewer vectors.
    pub fn search(&self, query: &[f32], k: usize) -> Vec<Neighbour> {
        let lists = self.list_starts.len() - 1;
        let mut probed: Vec<usize> = if self.centroids.is_empty() {
            (0..lists).collect()
        } else {
            let mut ranked: Vec<(f32, usize)> = self.centroids.chunks_exact(self.dim).map(|centroid| squared_distance(query, centroid)).zip(0..).collect();
            ranked.sort_by(|a, b| a.0.total_cmp(&b.0).then(a.1.cmp(&b.1)));
            ranked.into_iter().take(self.nprobe).map(|(_, list)| list).collect()
        };
        probed.dedup();
        let mut best: Vec<Neighbour> = Vec::with_capacity(k + 1);
        for list in probed {
            for slot in self.list_starts[list]..self.list_starts[list + 1] {
                let distance = squared_distance(query, self.vector(slot));
                if best.len() == k && distance >= best[k - 1].distance {
                    continue;
                }
                let position = best.partition_point(|neighbour| neighbour.distance <= distance);
                best.insert(position, Neighbour { distance, id: self.ids[slot], slot });
                best.truncate(k);
            }
        }
        best
    }

    /// Replaces each `dim`-wide frame of `features` with
    /// `rate * (weighted mean of its neighbours) + (1 - rate) * frame`, where the weights
    /// are the inverse squares of the reported distances, normalised per frame.
    pub fn blend(&self, features: &mut [f32], rate: f32) -> Result<()> {
        if !features.len().is_multiple_of(self.dim) {
            return Err(Error::invalid("feature width does not match the index"));
        }
        let mut mixed = vec![0.0f32; self.dim];
        for frame in features.chunks_exact_mut(self.dim) {
            let neighbours = self.search(frame, NEIGHBOURS);
            let weights: Vec<f32> = neighbours.iter().map(|neighbour| (1.0 / neighbour.distance) * (1.0 / neighbour.distance)).collect();
            let total: f32 = weights.iter().sum();
            mixed.fill(0.0);
            for (neighbour, weight) in neighbours.iter().zip(&weights) {
                let weight = weight / total;
                for (sum, value) in mixed.iter_mut().zip(self.vector(neighbour.slot)) {
                    *sum += weight * value;
                }
            }
            for (value, blended) in frame.iter_mut().zip(&mixed) {
                *value = rate * blended + (1.0 - rate) * *value;
            }
        }
        Ok(())
    }
}

fn squared_distance(a: &[f32], b: &[f32]) -> f32 {
    // Four independent sums keep the loop vectorisable and the rounding stable.
    let mut sums = [0.0f32; 4];
    let (a_chunks, b_chunks) = (a.chunks_exact(4), b.chunks_exact(4));
    let tail: f32 = a_chunks.remainder().iter().zip(b_chunks.remainder()).map(|(x, y)| (x - y) * (x - y)).sum();
    for (x, y) in a_chunks.zip(b_chunks) {
        for lane in 0..4 {
            let difference = x[lane] - y[lane];
            sums[lane] += difference * difference;
        }
    }
    sums[0] + sums[1] + sums[2] + sums[3] + tail
}

#[cfg(test)]
mod tests {
    use super::*;

    fn flat_index(dim: usize, vectors: &[f32]) -> Vec<u8> {
        let total = vectors.len() / dim;
        let mut bytes = b"IxF2".to_vec();
        bytes.extend((dim as i32).to_le_bytes());
        bytes.extend((total as u64).to_le_bytes());
        bytes.extend([0u8; 16]);
        bytes.push(1);
        bytes.extend(1i32.to_le_bytes());
        bytes.extend((vectors.len() as u64).to_le_bytes());
        for value in vectors {
            bytes.extend(value.to_le_bytes());
        }
        bytes
    }

    #[test]
    fn flat_index_returns_neighbours_closest_first() {
        let index = FeatureIndex::from_bytes(&flat_index(2, &[0.0, 0.0, 3.0, 4.0, 1.0, 0.0])).unwrap();
        let found = index.search(&[0.9, 0.0], 2);
        assert_eq!(found.iter().map(|n| n.id).collect::<Vec<_>>(), vec![2, 0]);
        assert!((found[0].distance - 0.01).abs() < 1e-6);
        assert!((found[1].distance - 0.81).abs() < 1e-6);
    }

    #[test]
    fn blend_weights_by_inverse_squared_distance() {
        let index = FeatureIndex::from_bytes(&flat_index(1, &[1.0, 3.0])).unwrap();
        // Query 2.5: squared distances 2.25 and 0.25, weights 1/2.25^2 and 1/0.25^2.
        let mut features = vec![2.5f32];
        index.blend(&mut features, 0.5).unwrap();
        let (w1, w3) = (1.0 / (2.25f32 * 2.25), 1.0 / (0.25f32 * 0.25));
        let neighbours = (w1 * 1.0 + w3 * 3.0) / (w1 + w3);
        assert!((features[0] - (0.5 * neighbours + 0.5 * 2.5)).abs() < 1e-6);
    }

    #[test]
    fn an_empty_index_is_refused() {
        assert!(matches!(FeatureIndex::from_bytes(&flat_index(4, &[])), Err(Error::Invalid(_))));
        assert!(matches!(FeatureIndex::from_bytes(b"IxPQ0000"), Err(Error::Unsupported { .. })));
    }
}
