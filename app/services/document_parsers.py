"""Pluggable document → text parsers for RAG ingestion.

Every parser turns a file on disk into plain text (or markdown) that is then
chunked and embedded by ``app.services.rag.RAGService``. Keeping parsing behind
one interface lets ingestion swap implementations and lets us compare them end
to end with identical chunking/embedding (see ``scripts/compare_parsers.py``).

Parsers are synchronous (CPU-bound); call them via ``asyncio.to_thread`` from
async code.
"""

from abc import (
    ABC,
    abstractmethod,
)
from pathlib import Path
from typing import (
    Dict,
    List,
    Optional,
    Type,
    override,
)

from docling.datamodel.accelerator_options import (
    AcceleratorDevice,
    AcceleratorOptions,
)
from docling.datamodel.base_models import (
    ConversionStatus,
    InputFormat,
)
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import (
    DocumentConverter,
    PdfFormatOption,
)
from pypdf import PdfReader

from app.core.logging import logger


class DocumentParser(ABC):
    """Interface for turning a document file into text for chunking and embedding."""

    name: str = ""

    @abstractmethod
    def parse(self, path: Path) -> str:
        """Extract text from ``path``.

        Args:
            path: The file to parse.

        Returns:
            str: Extracted text; "" if the document has no extractable text.
        """


class PypdfParser(DocumentParser):
    """Fast, dependency-light text-layer extraction. Loses layout, headings and table structure."""

    name = "pypdf"

    @override
    def parse(self, path: Path) -> str:
        """Concatenate the text layer of every page."""
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(p.strip() for p in pages if p.strip())


class DoclingParser(DocumentParser):
    """Layout-aware parsing via docling, exported as markdown (headings, lists, tables preserved).

    The converter (and its layout/table models) loads lazily on first use and is
    reused across calls. It defaults to CPU because PyTorch's MPS backend crashes
    on some macOS versions (``-[MPSNDArray arrayViewWithShape:strides:]:
    unrecognized selector``).
    """

    name = "docling"

    def __init__(self, do_ocr: bool = False, device: AcceleratorDevice = AcceleratorDevice.CPU):
        """Configure the docling pipeline.

        Args:
            do_ocr: OCR bitmap regions. Only needed for scanned PDFs; much slower.
            device: Accelerator for docling's models.
        """
        self._do_ocr = do_ocr
        self._device = device
        self._converter: Optional[DocumentConverter] = None

    def _get_converter(self) -> DocumentConverter:
        if self._converter is None:
            options = PdfPipelineOptions(
                do_ocr=self._do_ocr,
                do_table_structure=True,
                accelerator_options=AcceleratorOptions(device=self._device),
            )
            self._converter = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
            )
            logger.info("docling_converter_initialized", do_ocr=self._do_ocr, device=self._device.value)
        return self._converter

    @override
    def parse(self, path: Path) -> str:
        """Convert the document and export it as markdown without image placeholders."""
        result = self._get_converter().convert(str(path), raises_on_error=False)
        if result.status not in (ConversionStatus.SUCCESS, ConversionStatus.PARTIAL_SUCCESS):
            raise ValueError(f"docling conversion failed with status {result.status.value}")
        if result.status == ConversionStatus.PARTIAL_SUCCESS:
            logger.warning("docling_partial_conversion", path=str(path))
        return result.document.export_to_markdown(image_placeholder="", escape_underscores=False).strip()


PARSERS: Dict[str, Type[DocumentParser]] = {
    PypdfParser.name: PypdfParser,
    DoclingParser.name: DoclingParser,
}


def parser_names() -> List[str]:
    """Return the registered parser names."""
    return list(PARSERS)


def get_parser(name: str, do_ocr: bool = False) -> DocumentParser:
    """Instantiate a parser by name.

    Args:
        name: A key of ``PARSERS``.
        do_ocr: Passed to parsers that support OCR (docling); ignored otherwise.

    Raises:
        ValueError: If ``name`` isn't registered.
    """
    if name not in PARSERS:
        raise ValueError(f"unknown parser '{name}', expected one of {parser_names()}")
    if name == DoclingParser.name:
        return DoclingParser(do_ocr=do_ocr)
    return PARSERS[name]()
