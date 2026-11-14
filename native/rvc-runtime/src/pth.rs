//! Reads a PyTorch checkpoint (`.pth`) without PyTorch.
//!
//! A checkpoint is a zip archive holding one pickle stream (`data.pkl`) and one raw
//! file per tensor storage. The pickle stream is interpreted by a small stack machine
//! that knows the handful of constructors a tensor checkpoint needs and refuses
//! everything else, so loading a file can never run code from it.

use std::cell::RefCell;
use std::collections::HashMap;
use std::path::Path;
use std::rc::Rc;

use crate::error::{Error, Result};

const KIND: &str = "checkpoint";
/// Upper bound on any one tensor (elements); real voice models stay far below it.
const MAX_ELEMENTS: usize = 1 << 28;

/// A dense tensor converted to `f32`, row-major.
#[derive(Debug, Clone, PartialEq)]
pub struct Tensor {
    pub shape: Vec<usize>,
    pub data: Vec<f32>,
}

impl Tensor {
    pub fn len(&self) -> usize {
        self.data.len()
    }

    pub fn is_empty(&self) -> bool {
        self.data.is_empty()
    }
}

/// A value found in the checkpoint outside of the weights.
#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    None,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),
    Bytes(Vec<u8>),
    List(Vec<Value>),
    Dict(Vec<(Value, Value)>),
    Tensor(Tensor),
    /// A tensor storage that has not been turned into a tensor yet.
    Storage(Storage),
    /// A class or function named by the stream; only ever passed to [`reduce`].
    Global(String, String),
}

#[derive(Debug, Clone, PartialEq)]
pub struct Storage {
    dtype: Dtype,
    key: String,
}

#[derive(Debug, Clone, Copy, PartialEq)]
enum Dtype {
    F16,
    F32,
    F64,
    I64,
    I32,
    I16,
    I8,
    U8,
    Bool,
}

impl Dtype {
    fn from_storage(name: &str) -> Option<Self> {
        Some(match name {
            "HalfStorage" => Dtype::F16,
            "FloatStorage" => Dtype::F32,
            "DoubleStorage" => Dtype::F64,
            "LongStorage" => Dtype::I64,
            "IntStorage" => Dtype::I32,
            "ShortStorage" => Dtype::I16,
            "CharStorage" => Dtype::I8,
            "ByteStorage" => Dtype::U8,
            "BoolStorage" => Dtype::Bool,
            _ => return None,
        })
    }

    fn size(self) -> usize {
        match self {
            Dtype::F64 | Dtype::I64 => 8,
            Dtype::F32 | Dtype::I32 => 4,
            Dtype::F16 | Dtype::I16 => 2,
            Dtype::I8 | Dtype::U8 | Dtype::Bool => 1,
        }
    }

    fn read(self, bytes: &[u8]) -> f32 {
        match self {
            Dtype::F16 => half_to_f32(u16::from_le_bytes([bytes[0], bytes[1]])),
            Dtype::F32 => f32::from_le_bytes(bytes[..4].try_into().unwrap()),
            Dtype::F64 => f64::from_le_bytes(bytes[..8].try_into().unwrap()) as f32,
            Dtype::I64 => i64::from_le_bytes(bytes[..8].try_into().unwrap()) as f32,
            Dtype::I32 => i32::from_le_bytes(bytes[..4].try_into().unwrap()) as f32,
            Dtype::I16 => i16::from_le_bytes([bytes[0], bytes[1]]) as f32,
            Dtype::I8 => bytes[0] as i8 as f32,
            Dtype::U8 | Dtype::Bool => bytes[0] as f32,
        }
    }
}

/// IEEE 754 binary16 to binary32.
pub(crate) fn half_to_f32(bits: u16) -> f32 {
    let sign = ((bits >> 15) as u32) << 31;
    let exponent = ((bits >> 10) & 0x1f) as u32;
    let fraction = (bits & 0x3ff) as u32;
    let value = match (exponent, fraction) {
        (0, 0) => 0,
        (0, _) => {
            // Subnormal: shift the fraction up until its leading bit becomes the implicit one.
            let shift = fraction.leading_zeros() - 21;
            let fraction = (fraction << shift) & 0x3ff;
            ((113 - shift) << 23) | (fraction << 13)
        }
        (0x1f, _) => (0xff << 23) | (fraction << 13),
        _ => ((exponent + 112) << 23) | (fraction << 13),
    };
    f32::from_bits(sign | value)
}

impl Value {
    pub fn as_i64(&self) -> Option<i64> {
        match self {
            Value::Int(value) => Some(*value),
            Value::Bool(value) => Some(*value as i64),
            Value::Float(value) if value.fract() == 0.0 => Some(*value as i64),
            _ => None,
        }
    }

    pub fn as_f64(&self) -> Option<f64> {
        match self {
            Value::Float(value) => Some(*value),
            Value::Int(value) => Some(*value as f64),
            _ => None,
        }
    }

    pub fn as_str(&self) -> Option<&str> {
        match self {
            Value::Str(value) => Some(value),
            _ => None,
        }
    }

    pub fn as_list(&self) -> Option<&[Value]> {
        match self {
            Value::List(items) => Some(items),
            _ => None,
        }
    }

    /// Looks a string key up in a dictionary value.
    pub fn get(&self, key: &str) -> Option<&Value> {
        match self {
            Value::Dict(items) => items.iter().find(|(name, _)| name.as_str() == Some(key)).map(|(_, value)| value),
            _ => None,
        }
    }
}

/// Reads the top-level object of a checkpoint file.
pub fn load(path: &Path) -> Result<Value> {
    load_bytes(&std::fs::read(path)?)
}

/// Reads the top-level object of a checkpoint held in memory.
pub fn load_bytes(bytes: &[u8]) -> Result<Value> {
    if !bytes.starts_with(b"PK") {
        return Err(Error::unsupported(KIND, "not a zip-format PyTorch checkpoint (legacy or foreign format)"));
    }
    let archive = Archive::open(bytes)?;
    let pickle = archive.entry_named("data.pkl")?;
    Machine { archive: &archive, input: pickle, at: 0, stack: Vec::new(), marks: Vec::new(), memo: HashMap::new() }.run()
}

/// The stored (uncompressed) entries of a zip archive, by name.
struct Archive<'a> {
    bytes: &'a [u8],
    entries: HashMap<String, (usize, usize)>,
}

impl<'a> Archive<'a> {
    fn open(bytes: &'a [u8]) -> Result<Self> {
        let bad = |detail: &str| Error::format(KIND, format!("zip: {detail}"));
        let u16_at = |at: usize| bytes.get(at..at + 2).map(|b| u16::from_le_bytes([b[0], b[1]]) as usize);
        let u32_at = |at: usize| bytes.get(at..at + 4).map(|b| u32::from_le_bytes(b.try_into().unwrap()) as usize);
        let u64_at = |at: usize| bytes.get(at..at + 8).map(|b| u64::from_le_bytes(b.try_into().unwrap()) as usize);
        let floor = bytes.len().saturating_sub(22 + 65_535);
        let end = (floor..=bytes.len().saturating_sub(22))
            .rev()
            .find(|&at| bytes[at..at + 4] == [0x50, 0x4b, 0x05, 0x06])
            .ok_or_else(|| bad("no end of central directory"))?;
        let mut count = u16_at(end + 10).unwrap();
        let mut offset = u32_at(end + 16).unwrap();
        if count == 0xffff || offset == 0xffff_ffff {
            // Zip64: the locator sits right before the end record and points at the real one.
            let locator = end.checked_sub(20).filter(|&at| bytes[at..at + 4] == [0x50, 0x4b, 0x06, 0x07]);
            let record = locator.and_then(|at| u64_at(at + 8)).ok_or_else(|| bad("missing zip64 locator"))?;
            if bytes.get(record..record + 4) != Some(&[0x50, 0x4b, 0x06, 0x06]) {
                return Err(bad("missing zip64 end record"));
            }
            count = u64_at(record + 32).ok_or_else(|| bad("truncated zip64 record"))?;
            offset = u64_at(record + 48).ok_or_else(|| bad("truncated zip64 record"))?;
        }
        let mut entries = HashMap::new();
        let mut at = offset;
        for _ in 0..count {
            if bytes.get(at..at + 4) != Some(&[0x50, 0x4b, 0x01, 0x02]) {
                return Err(bad("bad central directory entry"));
            }
            let truncated = || bad("truncated central directory");
            let method = u16_at(at + 10).ok_or_else(truncated)?;
            let mut size = u32_at(at + 24).ok_or_else(truncated)?;
            let name_len = u16_at(at + 28).ok_or_else(truncated)?;
            let extra_len = u16_at(at + 30).ok_or_else(truncated)?;
            let comment_len = u16_at(at + 32).ok_or_else(truncated)?;
            let mut header = u32_at(at + 42).ok_or_else(truncated)?;
            let name = bytes.get(at + 46..at + 46 + name_len).ok_or_else(truncated)?;
            let extra = bytes.get(at + 46 + name_len..at + 46 + name_len + extra_len).ok_or_else(truncated)?;
            if size == 0xffff_ffff || header == 0xffff_ffff {
                // Zip64 extra field: 8-byte values for exactly the fields that overflowed, in order.
                let mut field = 0;
                while field + 4 <= extra.len() {
                    let id = u16::from_le_bytes([extra[field], extra[field + 1]]);
                    let len = u16::from_le_bytes([extra[field + 2], extra[field + 3]]) as usize;
                    if id == 1 {
                        let mut cursor = field + 4;
                        let mut next = || {
                            let value = extra.get(cursor..cursor + 8).map(|b| u64::from_le_bytes(b.try_into().unwrap()) as usize);
                            cursor += 8;
                            value.ok_or_else(|| bad("truncated zip64 field"))
                        };
                        if size == 0xffff_ffff {
                            size = next()?;
                            next()?; // compressed size, equal for stored entries
                        }
                        if header == 0xffff_ffff {
                            header = next()?;
                        }
                    }
                    field += 4 + len;
                }
            }
            if method != 0 {
                return Err(Error::unsupported(KIND, "compressed zip entries"));
            }
            let local_name = u16_at(header + 26).ok_or_else(truncated)?;
            let local_extra = u16_at(header + 28).ok_or_else(truncated)?;
            let start = header + 30 + local_name + local_extra;
            if start.checked_add(size).is_none_or(|stop| stop > bytes.len()) {
                return Err(bad("entry runs past the end of the file"));
            }
            entries.insert(String::from_utf8_lossy(name).into_owned(), (start, size));
            at += 46 + name_len + extra_len + comment_len;
        }
        Ok(Archive { bytes, entries })
    }

    /// The entry whose path ends in `/<name>`; PyTorch nests everything under one folder.
    fn entry_named(&self, name: &str) -> Result<&'a [u8]> {
        let suffix = format!("/{name}");
        self.entries
            .iter()
            .find(|(path, _)| path.ends_with(&suffix) || path.as_str() == name)
            .map(|(_, &(start, size))| &self.bytes[start..start + size])
            .ok_or_else(|| Error::format(KIND, format!("missing archive entry {name}")))
    }
}

/// What sits on the pickle stack. Containers are shared so that a memoised list or
/// dict filled in after it was memoised is seen complete by every later reference.
#[derive(Debug, Clone)]
enum Item {
    Leaf(Rc<Value>),
    Tuple(Rc<Vec<Item>>),
    List(Rc<RefCell<Vec<Item>>>),
    Dict(Rc<RefCell<Vec<(Item, Item)>>>),
}

impl Item {
    fn leaf(value: Value) -> Self {
        Item::Leaf(Rc::new(value))
    }

    fn into_value(self, depth: usize) -> Result<Value> {
        if depth > 64 {
            return Err(bad("nesting too deep"));
        }
        let many = |items: Vec<Item>| items.into_iter().map(|item| item.into_value(depth + 1)).collect::<Result<Vec<_>>>();
        Ok(match self {
            Item::Leaf(value) => Rc::try_unwrap(value).unwrap_or_else(|shared| (*shared).clone()),
            Item::Tuple(items) => Value::List(many(Rc::try_unwrap(items).unwrap_or_else(|shared| (*shared).clone()))?),
            Item::List(items) => Value::List(many(items.take())?),
            Item::Dict(items) => {
                let mut pairs = Vec::new();
                for (key, value) in items.take() {
                    pairs.push((key.into_value(depth + 1)?, value.into_value(depth + 1)?));
                }
                Value::Dict(pairs)
            }
        })
    }

    fn value(&self) -> Option<&Value> {
        match self {
            Item::Leaf(value) => Some(value),
            _ => None,
        }
    }

    fn integer(&self) -> Option<usize> {
        self.value().and_then(Value::as_i64).and_then(|n| usize::try_from(n).ok())
    }
}

struct Machine<'a> {
    archive: &'a Archive<'a>,
    input: &'a [u8],
    at: usize,
    stack: Vec<Item>,
    marks: Vec<usize>,
    memo: HashMap<u32, Item>,
}

fn bad(detail: impl std::fmt::Display) -> Error {
    Error::format(KIND, format!("pickle: {detail}"))
}

impl Machine<'_> {
    fn take(&mut self, count: usize) -> Result<&[u8]> {
        let bytes = self.input.get(self.at..self.at + count).ok_or_else(|| bad("truncated stream"))?;
        self.at += count;
        Ok(bytes)
    }

    fn byte(&mut self) -> Result<u8> {
        Ok(self.take(1)?[0])
    }

    fn u32(&mut self) -> Result<u32> {
        Ok(u32::from_le_bytes(self.take(4)?.try_into().unwrap()))
    }

    fn line(&mut self) -> Result<String> {
        let rest = &self.input[self.at..];
        let end = rest.iter().position(|&b| b == b'\n').ok_or_else(|| bad("unterminated line"))?;
        let text = String::from_utf8_lossy(&rest[..end]).into_owned();
        self.at += end + 1;
        Ok(text)
    }

    fn text(&mut self, count: usize) -> Result<()> {
        let text = String::from_utf8_lossy(self.take(count)?).into_owned();
        self.push(Value::Str(text));
        Ok(())
    }

    fn pop(&mut self) -> Result<Item> {
        self.stack.pop().ok_or_else(|| bad("stack underflow"))
    }

    fn pop_mark(&mut self) -> Result<Vec<Item>> {
        let mark = self.marks.pop().ok_or_else(|| bad("missing mark"))?;
        if mark > self.stack.len() {
            return Err(bad("mark above stack"));
        }
        Ok(self.stack.split_off(mark))
    }

    fn push(&mut self, value: Value) {
        self.stack.push(Item::leaf(value));
    }

    fn top_dict(&mut self) -> Result<Rc<RefCell<Vec<(Item, Item)>>>> {
        match self.stack.last() {
            Some(Item::Dict(items)) => Ok(items.clone()),
            _ => Err(bad("expected a dict on the stack")),
        }
    }

    fn top_list(&mut self) -> Result<Rc<RefCell<Vec<Item>>>> {
        match self.stack.last() {
            Some(Item::List(items)) => Ok(items.clone()),
            _ => Err(bad("expected a list on the stack")),
        }
    }

    fn run(mut self) -> Result<Value> {
        loop {
            let opcode = self.byte()?;
            match opcode {
                0x80 => {
                    self.byte()?; // PROTO
                }
                0x95 => {
                    self.take(8)?; // FRAME
                }
                b'.' => {
                    let top = self.pop()?;
                    self.memo.clear();
                    self.stack.clear();
                    return top.into_value(0);
                }
                b'(' => self.marks.push(self.stack.len()),
                b'N' => self.push(Value::None),
                0x88 => self.push(Value::Bool(true)),
                0x89 => self.push(Value::Bool(false)),
                b'K' => {
                    let value = self.byte()? as i64;
                    self.push(Value::Int(value));
                }
                b'M' => {
                    let bytes = self.take(2)?;
                    let value = u16::from_le_bytes([bytes[0], bytes[1]]) as i64;
                    self.push(Value::Int(value));
                }
                b'J' => {
                    let value = self.u32()? as i32 as i64;
                    self.push(Value::Int(value));
                }
                0x8a => {
                    let count = self.byte()? as usize;
                    if count > 8 {
                        return Err(bad("integer wider than 64 bits"));
                    }
                    let bytes = self.take(count)?;
                    let negative = bytes.last().is_some_and(|&b| b & 0x80 != 0);
                    let mut wide = [if negative { 0xff } else { 0 }; 8];
                    wide[..count].copy_from_slice(bytes);
                    self.push(Value::Int(i64::from_le_bytes(wide)));
                }
                b'G' => {
                    let value = f64::from_be_bytes(self.take(8)?.try_into().unwrap());
                    self.push(Value::Float(value));
                }
                b'X' | b'T' => {
                    let count = self.u32()? as usize;
                    self.text(count)?;
                }
                0x8c | b'U' => {
                    let count = self.byte()? as usize;
                    self.text(count)?;
                }
                b'B' | b'C' => {
                    let count = if opcode == b'B' { self.u32()? as usize } else { self.byte()? as usize };
                    let bytes = self.take(count)?.to_vec();
                    self.push(Value::Bytes(bytes));
                }
                b'}' => self.stack.push(Item::Dict(Rc::default())),
                b']' => self.stack.push(Item::List(Rc::default())),
                b')' => self.stack.push(Item::Tuple(Rc::default())),
                0x85 | 0x86 | 0x87 => {
                    let count = (opcode - 0x84) as usize;
                    if self.stack.len() < count {
                        return Err(bad("stack underflow"));
                    }
                    let items = self.stack.split_off(self.stack.len() - count);
                    self.stack.push(Item::Tuple(Rc::new(items)));
                }
                b't' => {
                    let items = self.pop_mark()?;
                    self.stack.push(Item::Tuple(Rc::new(items)));
                }
                b'l' => {
                    let items = self.pop_mark()?;
                    self.stack.push(Item::List(Rc::new(RefCell::new(items))));
                }
                b'a' => {
                    let value = self.pop()?;
                    self.top_list()?.borrow_mut().push(value);
                }
                b'e' => {
                    let items = self.pop_mark()?;
                    self.top_list()?.borrow_mut().extend(items);
                }
                b's' => {
                    let value = self.pop()?;
                    let key = self.pop()?;
                    self.top_dict()?.borrow_mut().push((key, value));
                }
                b'u' => {
                    let items = self.pop_mark()?;
                    if items.len() % 2 != 0 {
                        return Err(bad("odd number of dict items"));
                    }
                    let dict = self.top_dict()?;
                    let mut items = items.into_iter();
                    while let (Some(key), Some(value)) = (items.next(), items.next()) {
                        dict.borrow_mut().push((key, value));
                    }
                }
                b'q' => {
                    let key = self.byte()? as u32;
                    self.remember(key)?;
                }
                b'r' => {
                    let key = self.u32()?;
                    self.remember(key)?;
                }
                0x94 => {
                    let key = self.memo.len() as u32;
                    self.remember(key)?;
                }
                b'h' => {
                    let key = self.byte()? as u32;
                    self.recall(key)?;
                }
                b'j' => {
                    let key = self.u32()?;
                    self.recall(key)?;
                }
                b'c' => {
                    let module = self.line()?;
                    let name = self.line()?;
                    self.push(Value::Global(module, name));
                }
                0x93 => {
                    let name = self.pop()?;
                    let module = self.pop()?;
                    match (module.value(), name.value()) {
                        (Some(Value::Str(module)), Some(Value::Str(name))) => self.push(Value::Global(module.clone(), name.clone())),
                        _ => return Err(bad("global name is not text")),
                    }
                }
                b'Q' => {
                    let id = self.pop()?;
                    let storage = self.storage(id)?;
                    self.push(storage);
                }
                b'R' | 0x81 => {
                    let Item::Tuple(arguments) = self.pop()? else { return Err(bad("call arguments are not a tuple")) };
                    let callee = self.pop()?;
                    let item = self.reduce(callee, &arguments)?;
                    self.stack.push(item);
                }
                b'b' => {
                    // BUILD only attaches attributes (state_dict metadata); the object stays as is.
                    self.pop()?;
                }
                other => return Err(Error::unsupported(KIND, format!("pickle opcode 0x{other:02x}"))),
            }
        }
    }

    fn remember(&mut self, key: u32) -> Result<()> {
        let top = self.stack.last().ok_or_else(|| bad("stack underflow"))?.clone();
        self.memo.insert(key, top);
        Ok(())
    }

    fn recall(&mut self, key: u32) -> Result<()> {
        let item = self.memo.get(&key).ok_or_else(|| bad("unknown memo key"))?.clone();
        self.stack.push(item);
        Ok(())
    }

    /// `('storage', <storage class>, key, location, element count)`
    fn storage(&mut self, id: Item) -> Result<Value> {
        let Item::Tuple(parts) = id else { return Err(bad("persistent id is not a tuple")) };
        let part = |index: usize| parts.get(index).and_then(Item::value);
        match (part(0), part(1), part(2)) {
            (Some(Value::Str(tag)), Some(Value::Global(module, class)), Some(Value::Str(key))) if tag == "storage" && module == "torch" => {
                let dtype = Dtype::from_storage(class).ok_or_else(|| Error::unsupported(KIND, format!("storage type {class}")))?;
                Ok(Value::Storage(Storage { dtype, key: key.clone() }))
            }
            _ => Err(bad("unrecognised persistent id")),
        }
    }

    fn reduce(&mut self, callee: Item, arguments: &[Item]) -> Result<Item> {
        let Some(Value::Global(module, name)) = callee.value() else { return Err(bad("callee is not a global")) };
        match (module.as_str(), name.as_str()) {
            ("collections", "OrderedDict") => Ok(Item::Dict(Rc::default())),
            ("torch._utils", "_rebuild_tensor_v2") => {
                if arguments.len() < 4 {
                    return Err(bad("tensor constructor is missing arguments"));
                }
                self.tensor(&arguments[0], &arguments[1], &arguments[2], &arguments[3]).map(Item::leaf)
            }
            // A parameter is its tensor; `requires_grad` and hooks do not matter for inference.
            ("torch._utils", "_rebuild_parameter") => arguments.first().cloned().ok_or_else(|| bad("parameter without data")),
            _ => Err(Error::unsupported(KIND, format!("pickled object {module}.{name}"))),
        }
    }

    fn tensor(&mut self, storage: &Item, offset: &Item, shape: &Item, stride: &Item) -> Result<Value> {
        let Some(Value::Storage(storage)) = storage.value() else { return Err(bad("tensor without storage")) };
        let dims = |item: &Item| -> Result<Vec<usize>> {
            let Item::Tuple(items) = item else { return Err(bad("tensor shape is not a tuple")) };
            items.iter().map(|item| item.integer().ok_or_else(|| bad("bad tensor dimension"))).collect()
        };
        let shape = dims(shape)?;
        let stride = dims(stride)?;
        let offset = offset.integer().ok_or_else(|| bad("bad tensor offset"))?;
        if stride.len() != shape.len() {
            return Err(bad("tensor stride does not match its shape"));
        }
        let count = shape.iter().try_fold(1usize, |total, &dim| total.checked_mul(dim)).filter(|&total| total <= MAX_ELEMENTS).ok_or_else(|| bad("tensor too large"))?;
        let bytes = self.archive.entry_named(&format!("data/{}", storage.key))?;
        let width = storage.dtype.size();
        let mut data = Vec::with_capacity(count);
        let mut index = vec![0usize; shape.len()];
        for _ in 0..count {
            let element = offset + index.iter().zip(&stride).map(|(i, s)| i * s).sum::<usize>();
            let chunk = element.checked_mul(width).and_then(|start| bytes.get(start..start + width)).ok_or_else(|| bad("tensor reads past its storage"))?;
            data.push(storage.dtype.read(chunk));
            for axis in (0..shape.len()).rev() {
                index[axis] += 1;
                if index[axis] < shape[axis] {
                    break;
                }
                index[axis] = 0;
            }
        }
        Ok(Value::Tensor(Tensor { shape, data }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn half_precision_values_convert_exactly() {
        assert_eq!(half_to_f32(0x3c00), 1.0);
        assert_eq!(half_to_f32(0xc000), -2.0);
        assert_eq!(half_to_f32(0x0001), 5.960_464_5e-8);
        assert_eq!(half_to_f32(0x7bff), 65504.0);
        assert_eq!(half_to_f32(0x0000), 0.0);
        assert!(half_to_f32(0x7c00).is_infinite());
        assert!(half_to_f32(0x7e00).is_nan());
    }

    #[test]
    fn rejects_files_that_are_not_checkpoints() {
        assert!(matches!(load_bytes(b"not a zip"), Err(Error::Unsupported { .. })));
        assert!(matches!(load_bytes(b"PK\x03\x04 truncated"), Err(Error::Format { .. })));
    }
}
