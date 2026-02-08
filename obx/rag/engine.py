import shutil
import os
import json
import time
import asyncio
import threading
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime

# Third-party imports
try:
    from txtai.embeddings import Embeddings # type: ignore
except ImportError:
    Embeddings = None

try:
    from chonkie import SemanticChunker # type: ignore
except ImportError:
    SemanticChunker = None

try:
    from markitdown import MarkItDown # type: ignore
except ImportError:
    MarkItDown = None

try:
    from pydantic_ai import Embedder
except ImportError:
    Embedder = None

from rich.progress import Progress

from obx.core.config import settings, OBX_DIR

class RAG:
    def __init__(self):
        self.index_path = OBX_DIR / "txtai_index"
        self.tracker_path = OBX_DIR / "index_tracker.json"
        self.metadata_path = OBX_DIR / "metadata_store.json"
        
        if not Embeddings: raise ImportError("txtai not installed.")
        if not SemanticChunker: raise ImportError("chonkie not installed.")
        
        self._setup_env()
        
        # Configure txtai based on settings
        provider = settings.embedding_provider
        model = settings.embedding_model
        
        # Base config: keyword=True (Sparse/BM25), content=True (store metadata)
        self.txtai_config = {
            "content": True,
            "keyword": True
        }
        
        # Provider configuration
        if provider == "sentence-transformers":
            # Ensure full HF path if generic name provided
            if "/" not in model and not Path(model).exists():
                 self.txtai_config["path"] = f"sentence-transformers/{model}"
            else:
                 self.txtai_config["path"] = model
        elif provider == "openai":
            self.txtai_config["path"] = "txtai.embeddings.API"
            self.txtai_config["provider"] = "openai"
            self.txtai_config["key"] = settings.openai_api_key
            self.txtai_config["model"] = model
        elif provider == "cohere":
            self.txtai_config["path"] = "txtai.embeddings.API"
            self.txtai_config["provider"] = "cohere"
            self.txtai_config["key"] = settings.cohere_api_key
            self.txtai_config["model"] = model
        elif provider == "voyageai":
            print(f"Warning: Provider '{provider}' might not be natively supported by txtai config mapping. Trying as path.")
            self.txtai_config["path"] = model
        elif provider == "google":
             self.txtai_config["path"] = "txtai.embeddings.API"
             self.txtai_config["provider"] = "google" 
             self.txtai_config["key"] = settings.gemini_api_key
             self.txtai_config["model"] = model
        elif provider == "ollama":
             self.txtai_config["path"] = "txtai.embeddings.API"
             self.txtai_config["provider"] = "ollama"
             self.txtai_config["url"] = settings.ollama_url
             self.txtai_config["model"] = model
        else:
            # Safer fallback for unknown providers or custom usage
            # If it looks like a path or has a slash, use it directly
            if Path(model).exists() or "/" in model:
                self.txtai_config["path"] = model
            else:
                 # Otherwise assume it's a sentence-transformer model that needs prefix
                 # This covers the "all-MiniLM-L6-v2" case while allowing full paths
                 self.txtai_config["path"] = f"sentence-transformers/{model}"
            
            # Print warning if provider is not standard but we're trying fallback
            if provider not in ["sentence-transformers", "transformers", "huggingface"]:
                print(f"Note: Provider '{provider}' not explicitly mapped. Using model path strategy: {self.txtai_config['path']}")

        self.embeddings = Embeddings(self.txtai_config)
        
        self.chunker = SemanticChunker(threshold=0.7, chunk_size=512)
        self.markitdown = MarkItDown() if MarkItDown else None
        
        self.tracker = self._load_tracker()
        self.metadata_store = self._load_metadata()
        self._index_loaded = False
        # Guard txtai embeddings against concurrent access (non-thread-safe in practice)
        self._lock = threading.RLock()

    def _setup_env(self):
        if settings.openai_api_key: os.environ["OPENAI_API_KEY"] = settings.openai_api_key
        if settings.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
            if "GOOGLE_API_KEY" in os.environ:
               del os.environ["GOOGLE_API_KEY"]
        if settings.cohere_api_key: os.environ["CO_API_KEY"] = settings.cohere_api_key
        if settings.voyage_api_key: os.environ["VOYAGE_API_KEY"] = settings.voyage_api_key

        # Silence noisy HF/txtai model cache logs (not errors)
        logging.getLogger("hf_utils").setLevel(logging.ERROR)
        logging.getLogger("txtai").setLevel(logging.ERROR)
        logging.getLogger("txtai.pipeline.hf_utils").setLevel(logging.ERROR)
        logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
        logging.getLogger("transformers").setLevel(logging.ERROR)
        os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

    def _load_tracker(self) -> Dict[str, float]:
        if self.tracker_path.exists():
            try:
                return json.loads(self.tracker_path.read_text())
            except:
                return {}
        return {}

    def _save_tracker(self):
        self.tracker_path.write_text(json.dumps(self.tracker, indent=2))
        
    def _load_metadata(self) -> Dict[str, Any]:
        if self.metadata_path.exists():
            try:
                return json.loads(self.metadata_path.read_text())
            except:
                return {}
        return {}

    def _save_metadata(self):
        self.metadata_path.write_text(json.dumps(self.metadata_store, indent=2))

    def _get_vault_files(self) -> List[Path]:
        if not settings.vault_path:
            return []
        
        all_files = list(settings.vault_path.rglob("*.md")) + list(settings.vault_path.rglob("*.pdf"))
        
        if not settings.exclude_folders:
            return all_files
            
        # Convert exclusion strings to absolute paths
        excluded_paths = [settings.vault_path / ex for ex in settings.exclude_folders]
        
        filtered_files = []
        for f in all_files:
            try:
                # Check if file is inside any excluded directory
                is_excluded = False
                for ex_path in excluded_paths:
                    if f.is_relative_to(ex_path):
                        is_excluded = True
                        break
                
                if not is_excluded:
                    filtered_files.append(f)
                    
            except Exception:
                continue
                
        return filtered_files

    def clear(self):
        with self._lock:
            if self.index_path.exists():
                shutil.rmtree(self.index_path)
            if self.tracker_path.exists():
                self.tracker_path.unlink()
            if self.metadata_path.exists():
                self.metadata_path.unlink()
            
            self.tracker = {}
            self.metadata_store = {}
            # Re-init with config
            self.embeddings = Embeddings(self.txtai_config)
            self._index_loaded = True
            print("Index cleared.")

    async def ingest(self, clear: bool = False):
        if clear:
            self.clear()

        with self._lock:
            # Load existing index if not clearing
            if not clear and self.index_path.exists() and not self._index_loaded:
                self.embeddings.load(str(self.index_path))
                self._index_loaded = True

        print(f"Scanning vault at {settings.vault_path}...")
        files = self._get_vault_files()

        to_process = []
        for f in files:
            mtime = f.stat().st_mtime
            if str(f) not in self.tracker or self.tracker[str(f)] < mtime:
                to_process.append(f)

        if not to_process:
            print("No new or modified files to index.")
            return

        print(f"Found {len(to_process)} files to process.")

        documents_to_index = []
        new_tracker = self.tracker.copy()

        with Progress() as progress:
            task = progress.add_task("[cyan]Processing files...", total=len(to_process))

            for file_path in to_process:
                try:
                    text_content = ""
                    if file_path.suffix.lower() == ".md":
                        text_content = file_path.read_text(encoding="utf-8")
                    elif file_path.suffix.lower() == ".pdf":
                        if self.markitdown:
                            result = self.markitdown.convert(str(file_path))
                            text_content = result.text_content
                        else:
                            continue

                    if not text_content.strip():
                        progress.advance(task)
                        continue

                    chunks = self.chunker.chunk(text_content)

                    # Extract headers from the text for better source attribution
                    headers = self._extract_headers(text_content)

                    for i, chunk in enumerate(chunks):
                        doc_id = f"{file_path.name}#{i}"

                        # Find the nearest header for this chunk
                        chunk_header = self._find_nearest_header(chunk.start_index, headers)

                        metadata = {
                            "text": chunk.text,
                            "source": file_path.name,
                            "path": str(file_path),
                            "type": file_path.suffix,
                            "chunk_index": i,
                            "header": chunk_header
                        }

                        # Store metadata in sidecar
                        self.metadata_store[doc_id] = metadata

                        # For txtai, we just need text for hybrid search
                        # (uid, data, vector) -> (uid, metadata, None)
                        # We still pass metadata to txtai so it indexes 'text' field
                        documents_to_index.append((doc_id, metadata, None))

                    new_tracker[str(file_path)] = file_path.stat().st_mtime

                except Exception as e:
                    print(f"Error processing {file_path.name}: {e}")

                progress.advance(task)

        if documents_to_index:
            print(f"Indexing {len(documents_to_index)} chunks...")

            with self._lock:
                self.embeddings.index(documents_to_index)
                self.embeddings.save(str(self.index_path))

            self.tracker = new_tracker
            self._save_tracker()
            self._save_metadata()
            print("Indexing complete.")
        else:
            print("No valid chunks extracted.")
            
    def index_exists(self) -> bool:
        return self.index_path.exists()

    def _extract_headers(self, text: str) -> List[Tuple[int, str, str]]:
        """Extract headers from markdown text.
        Returns list of (char_position, header_level, header_text) tuples.
        """
        import re
        headers = []
        current_pos = 0
        
        for line in text.split('\n'):
            match = re.match(r'^(#{1,6})\s+(.*)', line)
            if match:
                level = match.group(1)
                header_text = match.group(2).strip()
                headers.append((current_pos, level, header_text))
            current_pos += len(line) + 1  # +1 for newline
        
        return headers
    
    def _find_nearest_header(self, chunk_start: int, headers: List[Tuple[int, str, str]]) -> Optional[str]:
        """Find the nearest header before the chunk position."""
        if not headers:
            return None
        
        # Find the last header that appears before or at the chunk start
        nearest = None
        for pos, level, text in headers:
            if pos <= chunk_start:
                nearest = text
            else:
                break
        
        return nearest

    def search(self, query: str, limit: int = 5, weights: float = 0.5) -> List[Dict[str, Any]]:
        with self._lock:
            if not self.index_path.exists():
                return []
                
            if not self._index_loaded:
                self.embeddings.load(str(self.index_path))
                self._index_loaded = True
                
            results = self.embeddings.search(query, limit, weights=weights)
        
        enriched = []
        for r in results:
             if isinstance(r, dict):
                 uid = r['id']
                 score = r['score']
             else:
                 uid, score = r
                 
             # Retrieve metadata from sidecar store
             meta = self.metadata_store.get(uid, {})
             if meta:
                 result_item = meta.copy()
                 result_item['score'] = score
                 # Ensure 'text' is present if not in meta (should be)
                 enriched.append(result_item)
             else:
                 # Fallback if somehow missing
                 enriched.append({"id": uid, "score": score, "text": r.get('text', ''), "source": "Unknown"})
        
        return enriched
