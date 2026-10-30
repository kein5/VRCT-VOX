"""Real FAISS sparse IVF regression; optional runtime, no weights or audio."""
import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec('faiss'), 'optional RVC runtime FAISS required')
class RetrievalProbeTests(unittest.TestCase):
    @staticmethod
    def sparse_index():
        import faiss
        import numpy as np
        quantizer = faiss.IndexFlatL2(2)
        quantizer.add(np.array([[0, 0], [100, 100]], dtype='float32'))
        index = faiss.IndexIVFFlat(quantizer, 2, 2)
        index.is_trained = True
        index.add(np.array([[1, 1]] + [[100+i, 100] for i in range(12)], dtype='float32'))
        return index

    def test_sparse_list_gets_complete_neighbors_after_configuration(self):
        import numpy as np
        from integrations.rvc.loader import configure_index_search, CheckedIndex
        index = self.sparse_index()
        query = np.array([[.5, .5]], dtype='float32')
        self.assertTrue((index.search(query, 8)[1] < 0).any())
        configure_index_search(index)
        checked = CheckedIndex(index, index.ntotal)
        score, ids = checked.search(query, 8)
        self.assertTrue((ids >= 0).all())
        self.assertTrue(np.isfinite(score).all())
        self.assertEqual(index.nprobe, 2)
        checked.require_success()

    def test_generic_wrapper_changes_real_ivf_parameter(self):
        import faiss
        from integrations.rvc.loader import configure_index_search
        index = self.sparse_index()
        wrapped = faiss.IndexPreTransform(index)
        configure_index_search(wrapped)
        self.assertEqual(faiss.extract_index_ivf(wrapped).nprobe, 2)
        self.assertFalse(hasattr(wrapped, 'nprobe'))

    def test_preserves_larger_existing_probe(self):
        import faiss
        from integrations.rvc.loader import configure_index_search
        index = faiss.IndexIVFFlat(faiss.IndexFlatL2(2), 2, 32)
        index.nprobe = 16
        configure_index_search(index)
        self.assertEqual(index.nprobe, 16)

    def test_normal_ivf_uses_eight_lists(self):
        import faiss
        from integrations.rvc.loader import configure_index_search
        index = faiss.IndexIVFFlat(faiss.IndexFlatL2(2), 2, 32)
        configure_index_search(index)
        self.assertEqual(index.nprobe, 8)

    def test_flat_index_unchanged(self):
        import faiss
        from integrations.rvc.loader import configure_index_search
        index = faiss.IndexFlatL2(2)
        configure_index_search(index)
        self.assertFalse(hasattr(index, 'nprobe'))


if __name__ == '__main__':
    unittest.main()
