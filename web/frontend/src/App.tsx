import { useCallback, useEffect, useState } from "react";
import ImageCard from "./components/ImageCard";
import UploadForm from "./components/UploadForm";

export interface OcrResult {
  bbox: number[][];
  text: string;
  confidence: number;
}

export type OcrStatus = "queued" | "processing" | "done" | "empty";

export interface ImageData {
  image_hash: string;
  description: string;
  filename: string;
  content_type: string;
  ocr_results: OcrResult[] | null;
  status: OcrStatus;
}

function deriveStatus(results: OcrResult[] | null): OcrStatus {
  if (results === null) return "queued";
  if (results.length === 0) return "empty";
  return "done";
}

export default function App() {
  const [images, setImages] = useState<ImageData[]>([]);

  const fetchImages = useCallback(async () => {
    const res = await fetch("/api/images");
    if (!res.ok) return;
    const data: Omit<ImageData, "status">[] = await res.json();
    setImages(
      data.map((img) => ({ ...img, status: deriveStatus(img.ocr_results) })),
    );
  }, []);

  useEffect(() => {
    fetchImages();
  }, [fetchImages]);

  useEffect(() => {
    let ws: WebSocket;
    let timeout: number;

    function connect() {
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(`${proto}//${location.host}/ws`);

      ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.type === "ocr_started") {
          setImages((prev) =>
            prev.map((img) =>
              img.image_hash === data.hash
                ? { ...img, status: "processing", ocr_results: null }
                : img,
            ),
          );
        } else if (data.type === "image_deleted") {
          setImages((prev) => prev.filter((img) => img.image_hash !== data.hash));
        } else if (data.type === "ocr_completed") {
          setImages((prev) =>
            prev.map((img) =>
              img.image_hash === data.hash
                ? {
                    ...img,
                    ocr_results: data.ocr_results,
                    status: deriveStatus(data.ocr_results),
                  }
                : img,
            ),
          );
        }
      };

      ws.onclose = () => {
        timeout = window.setTimeout(connect, 3000);
      };
    }

    connect();
    return () => {
      clearTimeout(timeout);
      ws?.close();
    };
  }, []);

  const handleUploaded = (img: Omit<ImageData, "status">) => {
    const entry: ImageData = { ...img, status: "queued" };
    setImages((prev) => {
      const idx = prev.findIndex((i) => i.image_hash === entry.image_hash);
      if (idx === -1) return [entry, ...prev];
      const next = [...prev];
      next.splice(idx, 1);
      return [entry, ...next];
    });
  };

  const handleDelete = async (image_hash: string) => {
    setImages((prev) => prev.filter((img) => img.image_hash !== image_hash));
    await fetch(`/api/images/${image_hash}`, { method: "DELETE" });
  };

  const handleRerun = async (image_hash: string) => {
    setImages((prev) =>
      prev.map((img) =>
        img.image_hash === image_hash
          ? { ...img, status: "queued", ocr_results: null }
          : img,
      ),
    );
    await fetch(`/api/images/${image_hash}/rerun`, { method: "POST" });
  };

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <h1>Cloud OCR</h1>
        </div>
        <p className="subtitle">
          Upload an image to extract text. Results stream in as soon as the
          worker finishes.
        </p>
      </header>

      <UploadForm onUploaded={handleUploaded} />

      {images.length === 0 ? (
        <div className="empty-state">
          <p>No images yet. Upload one above to get started.</p>
        </div>
      ) : (
        <div className="gallery">
          {images.map((img) => (
            <ImageCard
              key={img.image_hash}
              image={img}
              onRerun={handleRerun}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}
    </div>
  );
}
