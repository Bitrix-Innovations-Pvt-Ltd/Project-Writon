"use client";

import { useState } from "react";

export default function TranslatePage() {
    const [file, setFile] = useState<File | null>(null);
    const [log, setLog] = useState<string[]>([]);
    const [language, setLanguage] = useState("");
    const [ocrText, setOcrText] = useState("");
    const [translation, setTranslation] = useState("");
    const [loading, setLoading] = useState(false);
    const [downloading, setDownloading] = useState(false);

    const handleSubmit = async () => {
        if (!file) return;
        setLoading(true);
        setLog([]);
        setLanguage("");
        setOcrText("");
        setTranslation("");

        const formData = new FormData();
        formData.append("file", file);

        const response = await fetch("http://127.0.0.1:8000/api/v1/translate/process", {
            method: "POST",
            body: formData,
        });

        const reader = response.body?.getReader();
        const decoder = new TextDecoder();
        if (!reader) return;

        let buffer = "";
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const events = buffer.split("\n\n");
            buffer = events.pop() || "";

            for (const evt of events) {
                const eventMatch = evt.match(/event: (.+)/);
                const dataMatch = evt.match(/data: (.+)/);
                if (!eventMatch || !dataMatch) continue;

                const eventType = eventMatch[1];
                const rawData = dataMatch[1];

                if (eventType === "log") {
                    setLog((prev) => [...prev, rawData]);
                } else if (eventType === "language") {
                    setLanguage(JSON.parse(rawData));
                } else if (eventType === "ocr") {
                    setOcrText(JSON.parse(rawData));
                } else if (eventType === "translation") {
                    setTranslation(JSON.parse(rawData));
                } else if (eventType === "done") {
                    setLoading(false);
                } else if (eventType === "engine") {
                    setLog((prev) => [...prev, `Engine used: ${JSON.parse(rawData)}`]);
                } else if (eventType === "error") {
                    setLog((prev) => [...prev, `Error: ${JSON.parse(rawData)}`]);
                    setLoading(false);
                }
            }
        }
        setLoading(false);
    };

    const handleDownloadPdf = async () => {
        if (!translation) return;
        setDownloading(true);

        try {
            const response = await fetch("http://127.0.0.1:8000/api/v1/translate/download-pdf", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    text: translation,
                    title: "Translated Legal Document",
                }),
            });

            if (!response.ok) throw new Error("Failed to generate PDF");

            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "translated_document.pdf";
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);
        } catch (err) {
            setLog((prev) => [...prev, `PDF download failed: ${err}`]);
        } finally {
            setDownloading(false);
        }
    };

    return (
        <div style={{ maxWidth: 800, margin: "40px auto", padding: 20, fontFamily: "sans-serif" }}>
            <h1>Legal Document Translator</h1>

            <input
                type="file"
                accept="image/*,application/pdf"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            <button
                onClick={handleSubmit}
                disabled={!file || loading}
                style={{ marginLeft: 12, padding: "8px 16px" }}
            >
                {loading ? "Processing..." : "Translate"}
            </button>

            <div style={{ marginTop: 20 }}>
                {log.map((l, i) => (
                    <div key={i} style={{ color: "gray", fontSize: 14 }}>{l}</div>
                ))}
            </div>

            {ocrText && (
                <div style={{ marginTop: 20 }}>
                    <h3>Original Transcription {language && `(${language})`}</h3>
                    <pre style={{ whiteSpace: "pre-wrap", background: "#f5f5f5", padding: 12 }}>{ocrText}</pre>
                </div>
            )}

            {translation && (
                <div style={{ marginTop: 20 }}>
                    <h3>English Translation</h3>
                    <pre style={{ whiteSpace: "pre-wrap", background: "#f5f5f5", padding: 12 }}>{translation}</pre>

                    <button
                        onClick={handleDownloadPdf}
                        disabled={downloading}
                        style={{ marginTop: 12, padding: "8px 16px" }}
                    >
                        {downloading ? "Generating PDF..." : "Download as PDF"}
                    </button>
                </div>
            )}
        </div>
    );
}