import { useCallback, useEffect, useState } from "react";
import ImageCard from "./components/ImageCard";
import UploadForm from "./components/UploadForm";

export interface OcrResult {
  bbox: number[][];
  text: string;
  confidence: number;
}

export interface ImageData {
  image_hash: string;
  description: string;
  filename: string;
  content_type: string;
  ocr_results: OcrResult[] | null;
}

export default function App() {
  const [images, setImages] = useState<ImageData[]>([]);

  const fetchImages = useCallback(async () => {
    const res = await fetch("/api/images");
    if (res.ok) setImages(await res.json());
  }, []);

  useEffect(() => {
    fetchImages();
  }, [fetchImages]);

  // WebSocket for real-time OCR results
  useEffect(() => {
    let ws: WebSocket;
    let timeout: number;

    function connect() {
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(`${proto}//${location.host}/ws`);

      ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.type === "ocr_completed") {
          setImages((prev) =>
            prev.map((img) =>
              img.image_hash === data.hash
                ? { ...img, ocr_results: data.ocr_results }
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

  const handleUploaded = (img: ImageData) => {
    setImages((prev) => [img, ...prev]);
  };

  return (
    <div className="app">
      <h1>OCR App</h1>
      <UploadForm onUploaded={handleUploaded} />
      <div className="gallery">
        {images.map((img) => (
          <ImageCard key={img.image_hash} image={img} />
        ))}
      </div>
    </div>
  );
}
