import { useEffect, useRef } from "react";
import type { ImageData } from "../App";

interface Props {
  image: ImageData;
}

export default function ImageCard({ image }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  useEffect(() => {
    const results = image.ocr_results;
    if (!results || results.length === 0) return;

    const img = imgRef.current;
    const canvas = canvasRef.current;
    if (!img || !canvas) return;

    const draw = () => {
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      ctx.strokeStyle = "#00ff00";
      ctx.lineWidth = 2;
      ctx.font = "16px sans-serif";

      for (const r of results) {
        const b = r.bbox;
        // draw bounding polygon
        ctx.beginPath();
        ctx.moveTo(b[0][0], b[0][1]);
        for (let i = 1; i < b.length; i++) ctx.lineTo(b[i][0], b[i][1]);
        ctx.closePath();
        ctx.stroke();

        // label background
        const tw = ctx.measureText(r.text).width;
        ctx.fillStyle = "rgba(0,0,0,0.7)";
        ctx.fillRect(b[0][0], b[0][1] - 20, tw + 8, 22);

        // label text
        ctx.fillStyle = "#00ff00";
        ctx.fillText(r.text, b[0][0] + 4, b[0][1] - 4);
      }
    };

    if (img.complete && img.naturalWidth > 0) draw();
    else img.onload = draw;
  }, [image.ocr_results]);

  return (
    <div className="image-card">
      <div className="image-container">
        <img
          ref={imgRef}
          src={`/api/images/${image.image_hash}/image`}
          alt={image.description}
        />
        <canvas ref={canvasRef} />
      </div>
      <div className="image-info">
        <p className="description">{image.description}</p>
        {image.ocr_results === null && (
          <p className="status">OCR processing...</p>
        )}
        {image.ocr_results && image.ocr_results.length === 0 && (
          <p className="status">No text detected</p>
        )}
      </div>
    </div>
  );
}
