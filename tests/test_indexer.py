import tempfile, unittest
from pathlib import Path
from ai_workflow.indexer import build_indexes, load_state, row_fresh
import json

class IndexerTests(unittest.TestCase):
    def test_multi_language_indexing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'ai-workspace/generated').mkdir(parents=True)
            (root / 'server.ts').write_text('export const handleUser = async () => {}\nexport function getUser() {}\nrouter.get("/api/users")\n')
            (root / 'main.go').write_text('package main\nfunc (s *Server) StartServer() {}\nfunc HandleRoot() {}\n')
            (root / 'views.py').write_text('@api_router.post("/api/login")\nasync def login_view():\n    pass\n')
            stats = build_indexes(root)
            self.assertEqual(stats["files"], 3)
            symbols = [json.loads(l) for l in (root / 'ai-workspace/generated/symbol-index.jsonl').read_text().splitlines()]
            sym_names = {s["symbol"] for s in symbols}
            self.assertIn("handleUser", sym_names)
            self.assertIn("getUser", sym_names)
            self.assertIn("StartServer", sym_names)
            self.assertIn("HandleRoot", sym_names)
            self.assertIn("login_view", sym_names)

            endpoints = [json.loads(l) for l in (root / 'ai-workspace/generated/endpoint-index.jsonl').read_text().splitlines()]
            self.assertEqual(len(endpoints), 2)
            self.assertTrue(any(e["path"] == "/api/users" and e["method"] == "GET" for e in endpoints))
            self.assertTrue(any(e["path"] == "/api/login" and e["method"] == "POST" for e in endpoints))

    def test_stale_index_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'ai-workspace/generated').mkdir(parents=True)
            p=root/'app.py'; p.write_text('def hello():\n    return 1\n')
            build_indexes(root)
            row=json.loads((root/'ai-workspace/generated/symbol-index.jsonl').read_text().splitlines()[0])
            self.assertTrue(row_fresh(root,row,load_state(root)))
            p.write_text('def hello():\n    return 2\n')
            self.assertFalse(row_fresh(root,row,load_state(root)))
