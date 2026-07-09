"use client";

import { useRef, useState } from "react";

const API_BASE = "http://127.0.0.1:8000/api/v1/translate";

export default function TranslatePage() {
    // ---------------------------------------------------------------------
    // Document OCR + translation state
    // ---------------------------------------------------------------------
    const [file, setFile] = useState<File | null>(null);
    const [log, setLog] = useState<string[]>([]);
    const [language, setLanguage] = useState("");
    const [ocrText, setOcrText] = useState("");
    const [translation, setTranslation] = useState("");
    const [loading, setLoading] = useState(false);
    const [downloading, setDownloading] = useState(false);

    // ---------------------------------------------------------------------
    // Voice recording + transcription/translation state
    // ---------------------------------------------------------------------
    const [isRecording, setIsRecording] = useState(false);
    const [voiceLoading, setVoiceLoading] = useState(false);
    const [voiceError, setVoiceError] = useState("");
    const [hindiText, setHindiText] = useState("");
    const [englishText, setEnglishText] = useState("");
    const [voicePdfDownloading, setVoicePdfDownloading] = useState(false);
    const mediaRecorderRef = useRef<MediaRecorder | null>(null);
    const audioChunksRef = useRef<Blob[]>([]);

    const handleSubmit = async () => {
        if (!file) return;
        setLoading(true);
        setLog([]);
        setLanguage("");
        setOcrText("");
        setTranslation("");

        const formData = new FormData();
        formData.append("file", file);

        const response = await fetch(`${API_BASE}/process`, {
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
            const response = await fetch(`${API_BASE}/download-pdf`, {
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

    // ---------------------------------------------------------------------
    // Voice recording handlers -> POST /voice-to-english
    // ---------------------------------------------------------------------
    const startRecording = async () => {
        setVoiceError("");
        setHindiText("");
        setEnglishText("");

        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
            audioChunksRef.current = [];

            mediaRecorder.ondataavailable = (e) => {
                if (e.data.size > 0) audioChunksRef.current.push(e.data);
            };

            mediaRecorder.onstop = async () => {
                stream.getTracks().forEach((track) => track.stop());
                const audioBlob = new Blob(audioChunksRef.current, { type: "audio/webm" });
                await submitVoiceRecording(audioBlob);
            };

            mediaRecorder.start();
            mediaRecorderRef.current = mediaRecorder;
            setIsRecording(true);
        } catch (err) {
            setVoiceError(`Microphone access failed: ${err}`);
        }
    };

    const stopRecording = () => {
        mediaRecorderRef.current?.stop();
        setIsRecording(false);
    };

    const submitVoiceRecording = async (audioBlob: Blob) => {
        setVoiceLoading(true);
        setVoiceError("");

        try {
            const formData = new FormData();
            formData.append("file", audioBlob, "recording.webm");

            const response = await fetch(`${API_BASE}/voice-to-english`, {
                method: "POST",
                body: formData,
            });

            if (!response.ok) {
                const errBody = await response.json().catch(() => null);
                throw new Error(errBody?.detail || "Voice processing failed");
            }

            const data = await response.json();
            setHindiText(data.hindi_text);
            setEnglishText(data.english_text);
        } catch (err) {
            setVoiceError(`${err}`);
        } finally {
            setVoiceLoading(false);
        }
    };

    const handleVoiceSaveTxt = () => {
        const blob = new Blob([englishText], { type: "text/plain" });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "drafted_legal_facts.txt";
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
    };

    const handleVoiceSavePdf = async () => {
        if (!englishText) return;
        setVoicePdfDownloading(true);

        try {
            const response = await fetch(`${API_BASE}/download-pdf`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    text: englishText,
                    title: "Drafted Legal Facts",
                }),
            });

            if (!response.ok) throw new Error("Failed to generate PDF");

            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "drafted_legal_facts.pdf";
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);
        } catch (err) {
            setVoiceError(`PDF download failed: ${err}`);
        } finally {
            setVoicePdfDownloading(false);
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

            <hr style={{ margin: "40px 0" }} />

            <h2>Voice: Hindi Speech → English Facts</h2>

            <button
                onClick={isRecording ? stopRecording : startRecording}
                disabled={voiceLoading}
                style={{
                    padding: "8px 16px",
                    background: isRecording ? "#d33" : undefined,
                    color: isRecording ? "white" : undefined,
                }}
            >
                {isRecording ? "Stop Recording" : voiceLoading ? "Processing..." : "Start Recording"}
            </button>

            {voiceError && (
                <div style={{ color: "red", marginTop: 12 }}>{voiceError}</div>
            )}

            {hindiText && (
                <div style={{ marginTop: 20 }}>
                    <h3>Hindi Transcription</h3>
                    <pre style={{ whiteSpace: "pre-wrap", background: "#f5f5f5", padding: 12 }}>{hindiText}</pre>
                </div>
            )}

            <div style={{ marginTop: 20 }}>
                <h3>Drafted English Facts (editable)</h3>
                <textarea
                    value={englishText}
                    onChange={(e) => setEnglishText(e.target.value)}
                    placeholder="Click 'Start Recording' and speak in Hindi, or type your facts here manually..."
                    style={{
                        width: "100%",
                        minHeight: 200,
                        padding: 12,
                        fontFamily: "inherit",
                        fontSize: 14,
                        background: "#f5f5f5",
                        border: "1px solid #ccc",
                        borderRadius: 4,
                        boxSizing: "border-box",
                    }}
                />
                <div style={{ marginTop: 8 }}>
                    <button
                        onClick={handleVoiceSaveTxt}
                        disabled={!englishText}
                        style={{ padding: "8px 16px", marginRight: 8 }}
                    >
                        Save as TXT
                    </button>
                    <button
                        onClick={handleVoiceSavePdf}
                        disabled={!englishText || voicePdfDownloading}
                        style={{ padding: "8px 16px" }}
                    >
                        {voicePdfDownloading ? "Generating PDF..." : "Save as PDF"}
                    </button>
                </div>
            </div>
        </div>
    );
}