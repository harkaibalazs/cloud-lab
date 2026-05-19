import { useEffect, useMemo, useRef, useState } from "react";
import type { ImageData, OcrResult } from "../App";

interface Props {
  image: ImageData;
  onRerun: (image_hash: string) => void;
}

function StatusPill({ status }: { status: ImageData["status"] }) {
  const label =
    status === "queued"
      ? "Queued"
      : status === "processing"
        ? "Processing"
        : status === "empty"
          ? "No text"
          : "Done";
  return <span className={`pill pill-${status}`}>{label}</span>;
}

function joinText(results: OcrResult[]): string {
  return results.map((r) => r.text).join(" ");
}

export default function ImageCard({ image, onRerun }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const [copied, setCopied] = useState(false);
  const inFlight = image.status === "queued" || image.status === "processing";

  const fullText = useMemo(
    () => (image.ocr_results ? joinText(image.ocr_results) : ""),
    [image.ocr_results],
  );

  useEffect(() => {
    const results = image.ocr_results;
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img) return;

    const draw = () => {
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (!results || results.length === 0) return;

      ctx.strokeStyle = "rgba(37, 99, 235, 0.9)";
      ctx.fillStyle = "rgba(37, 99, 235, 0.12)";
      ctx.lineWidth = Math.max(2, canvas.width / 800);

      for (const r of results) {
        const b = r.bbox;
        ctx.beginPath();
        ctx.moveTo(b[0][0], b[0][1]);
        for (let i = 1; i < b.length; i++) ctx.lineTo(b[i][0], b[i][1]);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
      }
    };

    if (img.complete && img.naturalWidth > 0) draw();
    else img.onload = draw;
  }, [image.ocr_results]);

  const handleCopy = async () => {
    if (!fullText) return;
    try {
      await navigator.clipboard.writeText(fullText);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore */
    }
  };

  return (
    <article className="image-card">
      <div className="image-container">
        <img
          ref={imgRef}
          src={`/api/images/${image.image_hash}/image`}
          alt={image.description}
        />
        <canvas ref={canvasRef} />
        {inFlight && (
          <div className="processing-overlay">
            <div className="progress-bar">
              <div className="progress-fill" />
            </div>
            <span className="processing-label">
              {image.status === "queued" ? "Queued…" : "Running OCR…"}
            </span>
          </div>
        )}
      </div>

      <div className="image-body">
        <div className="image-meta">
          <div>
            <h3 className="description">{image.description}</h3>
            <p className="filename">{image.filename}</p>
          </div>
          <StatusPill status={image.status} />
        </div>

        <div className="ocr-section">
          <div className="ocr-header">
            <span className="ocr-label">Extracted text</span>
            <div className="ocr-actions">
              <button
                type="button"
                className="btn btn-ghost"
                onClick={handleCopy}
                disabled={!fullText}
              >
                {copied ? "Copied" : "Copy"}
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => onRerun(image.image_hash)}
                disabled={inFlight}
              >
                Re-run OCR
              </button>
            </div>
          </div>

          {image.status === "done" && (
            <p className="ocr-text">{fullText}</p>
          )}
          {image.status === "empty" && (
            <p className="ocr-text muted">No text detected in this image.</p>
          )}
          {inFlight && (
            <p className="ocr-text muted">
              Extracting text. This usually takes a few seconds…
            </p>
          )}
        </div>
      </div>
    </article>
  );
}
