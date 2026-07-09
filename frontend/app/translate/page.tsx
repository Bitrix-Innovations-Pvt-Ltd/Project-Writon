"use client";

import { useRef, useState } from "react";
import Navbar from "@/components/shared/Navbar";

const API_BASE = "http://127.0.0.1:8000/api/v1/translate";

export default function TranslatePage() {
    const [file, setFile] = useState<File | null>(null);
    const [log, setLog] = useState<string[]>([]);
    const [language, setLanguage] = useState("");
    const [ocrText, setOcrText] = useState("");
    const [translation, setTranslation] = useState("");
    const [loading, setLoading] = useState(false);
    const [downloading, setDownloading] = useState(false);

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

        const response = await fetch(`${API_BASE}/process`, { method: "POST", body: formData });
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

                if (eventType === "log") setLog((prev) => [...prev, rawData]);
                else if (eventType === "language") setLanguage(JSON.parse(rawData));
                else if (eventType === "ocr") setOcrText(JSON.parse(rawData));
                else if (eventType === "translation") setTranslation(JSON.parse(rawData));
                else if (eventType === "done") setLoading(false);
                else if (eventType === "engine") setLog((prev) => [...prev, `Engine used: ${JSON.parse(rawData)}`]);
                else if (eventType === "error") {
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
                body: JSON.stringify({ text: translation, title: "Translated Legal Document" }),
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
            const response = await fetch(`${API_BASE}/voice-to-english`, { method: "POST", body: formData });
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
                body: JSON.stringify({ text: englishText, title: "Drafted Legal Facts" }),
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
        <div className="font-body-md text-on-surface bg-[#FAF9F6] min-h-screen relative selection:bg-primary-fixed selection:text-on-primary-fixed">
            <div
                className="fixed inset-0 z-0 pointer-events-none opacity-[0.03]"
                style={{ backgroundImage: 'url("https://www.transparenttextures.com/patterns/parchment.png")' }}
            ></div>

            <div className="relative z-10 flex flex-col min-h-screen">
                <Navbar />

                <main className="max-w-[900px] mx-auto px-4 md:px-10 pt-16 pb-24 w-full">
                    <h1 className="font-display-lg text-4xl font-bold mb-2 text-on-background">
                        Legal Document Translator
                    </h1>
                    <p className="font-body-lg text-on-surface-variant mb-10">
                        Upload a scanned document or dictate facts in Hindi — get a clean English translation, ready to export.
                    </p>

                    {/* Document upload card */}
                    <div
                        className="bg-white p-8 rounded-xl border border-outline-variant mb-10"
                        style={{ boxShadow: "0 4px 12px rgba(20, 27, 46, 0.04)" }}
                    >
                        <h2 className="document-title font-document-title text-xl font-semibold mb-4">
                            Upload a Document
                        </h2>

                        <div className="flex items-center gap-3 mb-4">
                            <input
                                type="file"
                                accept="image/*,application/pdf"
                                onChange={(e) => setFile(e.target.files?.[0] || null)}
                                className="text-sm text-on-surface-variant"
                            />
                            <button
                                onClick={handleSubmit}
                                disabled={!file || loading}
                                className="py-2 px-5 bg-primary text-white text-sm font-semibold rounded-lg shadow-sm hover:bg-[#0a523f] transition-all duration-300 active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed"
                            >
                                {loading ? "Processing..." : "Translate"}
                            </button>
                        </div>

                        {log.length > 0 && (
                            <div className="text-xs text-outline space-y-1 mb-4">
                                {log.map((l, i) => <div key={i}>{l}</div>)}
                            </div>
                        )}

                        {ocrText && (
                            <div className="mb-4">
                                <h3 className="text-xs font-semibold uppercase text-on-surface-variant mb-2">
                                    Original Transcription {language && `(${language})`}
                                </h3>
                                <pre className="whitespace-pre-wrap bg-surface-container-low rounded-lg p-4 text-sm">
                                    {ocrText}
                                </pre>
                            </div>
                        )}

                        {translation && (
                            <div>
                                <h3 className="text-xs font-semibold uppercase text-on-surface-variant mb-2">
                                    English Translation
                                </h3>
                                <pre className="whitespace-pre-wrap bg-surface-container-low rounded-lg p-4 text-sm mb-3">
                                    {translation}
                                </pre>
                                <button
                                    onClick={handleDownloadPdf}
                                    disabled={downloading}
                                    className="py-2 px-5 border-2 border-primary text-primary text-sm font-semibold rounded-lg hover:bg-primary-fixed transition-all duration-300 active:scale-95 disabled:opacity-40"
                                >
                                    {downloading ? "Generating PDF..." : "Download as PDF"}
                                </button>
                            </div>
                        )}
                    </div>

                    {/* Voice facts card */}
                    <div
                        className="bg-white p-8 rounded-xl border border-outline-variant"
                        style={{ boxShadow: "0 4px 12px rgba(20, 27, 46, 0.04)" }}
                    >
                        <h2 className="font-document-title text-xl font-semibold mb-4">
                            Voice: Hindi Speech → English Facts
                        </h2>

                        <button
                            onClick={isRecording ? stopRecording : startRecording}
                            disabled={voiceLoading}
                            className={`py-2 px-5 text-sm font-semibold rounded-lg transition-all duration-300 active:scale-95 disabled:opacity-40 ${isRecording
                                    ? "bg-error text-white hover:bg-[#93000a]"
                                    : "bg-primary text-white hover:bg-[#0a523f]"
                                }`}
                        >
                            {isRecording ? "Stop Recording" : voiceLoading ? "Processing..." : "Start Recording"}
                        </button>

                        {voiceError && <div className="text-error text-sm mt-3">{voiceError}</div>}

                        {hindiText && (
                            <div className="mt-4">
                                <h3 className="text-xs font-semibold uppercase text-on-surface-variant mb-2">
                                    Hindi Transcription
                                </h3>
                                <pre className="whitespace-pre-wrap bg-surface-container-low rounded-lg p-4 text-sm">
                                    {hindiText}
                                </pre>
                            </div>
                        )}

                        <div className="mt-4">
                            <h3 className="text-xs font-semibold uppercase text-on-surface-variant mb-2">
                                Drafted English Facts (editable)
                            </h3>
                            <textarea
                                value={englishText}
                                onChange={(e) => setEnglishText(e.target.value)}
                                placeholder="Click 'Start Recording' and speak in Hindi, or type your facts here manually..."
                                className="w-full min-h-[200px] p-4 text-sm rounded-lg border border-outline-variant bg-surface-container-low font-body-md focus:outline-none focus:border-primary"
                            />
                            <div className="flex gap-3 mt-3">
                                <button
                                    onClick={handleVoiceSaveTxt}
                                    disabled={!englishText}
                                    className="py-2 px-5 border-2 border-primary text-primary text-sm font-semibold rounded-lg hover:bg-primary-fixed transition-all duration-300 active:scale-95 disabled:opacity-40"
                                >
                                    Save as TXT
                                </button>
                                <button
                                    onClick={handleVoiceSavePdf}
                                    disabled={!englishText || voicePdfDownloading}
                                    className="py-2 px-5 bg-primary text-white text-sm font-semibold rounded-lg shadow-sm hover:bg-[#0a523f] transition-all duration-300 active:scale-95 disabled:opacity-40"
                                >
                                    {voicePdfDownloading ? "Generating PDF..." : "Save as PDF"}
                                </button>
                            </div>
                        </div>
                    </div>
                </main>
            </div>
        </div>
    );
}