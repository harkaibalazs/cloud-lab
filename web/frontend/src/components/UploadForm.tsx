import { type FormEvent, useRef, useState } from "react";
import type { ImageData } from "../App";

interface Props {
  onUploaded: (image: ImageData) => void;
}

export default function UploadForm({ onUploaded }: Props) {
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const formRef = useRef<HTMLFormElement>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file || !description) return;

    setUploading(true);
    setError("");

    const body = new FormData();
    body.append("image", file);
    body.append("description", description);

    try {
      const res = await fetch("/api/upload", { method: "POST", body });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error || "Upload failed");
        return;
      }
      onUploaded({
        image_hash: data.image_hash,
        description,
        filename: file.name,
        content_type: file.type,
        ocr_results: null,
      });
      setDescription("");
      setFile(null);
      formRef.current?.reset();
    } catch {
      setError("Upload failed");
    } finally {
      setUploading(false);
    }
  };

  return (
    <form ref={formRef} onSubmit={handleSubmit} className="upload-form">
      <input
        type="file"
        accept="image/*"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
      />
      <input
        type="text"
        placeholder="Description"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />
      <button type="submit" disabled={uploading || !file || !description}>
        {uploading ? "Uploading..." : "Upload"}
      </button>
      {error && <p className="error">{error}</p>}
    </form>
  );
}
