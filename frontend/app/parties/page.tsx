"use client";

import { useState, useRef } from "react";
import Navbar from "@/components/shared/Navbar";

type Party = {
    serial_no: number;
    full_name: string;
    relation_type: string;
    relation_name: string;
    age: number | null;
    address: string;
    state: string;
    country: string;
    raw_text: string;
};

function PartyListEditor({ label }: { label: string }) {
    const [parties, setParties] = useState<Party[]>([]);
    const [activeSlide, setActiveSlide] = useState(0);
    const [tab, setTab] = useState<"type" | "upload" | "voice">("type");
    const [manualText, setManualText] = useState("");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const [recording, setRecording] = useState(false);

    const mediaRecorderRef = useRef<MediaRecorder | null>(null);
    const audioChunksRef = useRef<Blob[]>([]);

    const renumber = (list: Party[]) => list.map((p, i) => ({ ...p, serial_no: i + 1 }));

    const handleManualAdd = async () => {
        if (!manualText.trim()) return;
        setLoading(true);
        setError("");
        try {
            const res = await fetch("http://127.0.0.1:8000/api/v1/parties/validate-manual", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text: manualText }),
            });
            if (!res.ok) throw new Error((await res.json()).detail || "Failed to parse");
            const party: Party = await res.json();
            setParties((prev) => renumber([...prev, party]));
            setActiveSlide(parties.length);
            setManualText("");
        } catch (e: any) {
            setError(e.message || "Failed to add party");
        } finally {
            setLoading(false);
        }
    };

    const handleFileUpload = async (file: File) => {
        setLoading(true);
        setError("");
        const formData = new FormData();
        formData.append("file", file);
        try {
            const res = await fetch("http://127.0.0.1:8000/api/v1/parties/extract-ocr", {
                method: "POST",
                body: formData,
            });
            if (!res.ok) throw new Error((await res.json()).detail || "OCR extraction failed");
            const data = await res.json();
            setParties(renumber(data.parties));
            setActiveSlide(0);
        } catch (e: any) {
            setError(e.message || "Failed to extract from document");
        } finally {
            setLoading(false);
        }
    };

    const startRecording = async () => {
        setError("");
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const recorder = new MediaRecorder(stream);
        audioChunksRef.current = [];
        recorder.ondataavailable = (e) => audioChunksRef.current.push(e.data);
        recorder.onstop = async () => {
            const blob = new Blob(audioChunksRef.current, { type: "audio/webm" });
            setLoading(true);
            const formData = new FormData();
            formData.append("file", blob, "recording.webm");
            try {
                const res = await fetch("http://127.0.0.1:8000/api/v1/parties/extract-voice", {
                    method: "POST",
                    body: formData,
                });
                if (!res.ok) throw new Error((await res.json()).detail || "Voice extraction failed");
                const data = await res.json();
                setParties((prev) => renumber([...prev, ...data.parties]));
                setActiveSlide(parties.length);
            } catch (e: any) {
                setError(e.message || "Failed to extract from voice");
            } finally {
                setLoading(false);
            }
        };
        mediaRecorderRef.current = recorder;
        recorder.start();
        setRecording(true);
    };

    const stopRecording = () => {
        mediaRecorderRef.current?.stop();
        setRecording(false);
    };

    const updateActiveParty = (field: keyof Party, value: string | number | null) => {
        setParties((prev) => prev.map((p, i) => (i === activeSlide ? { ...p, [field]: value } : p)));
    };

    const removeActiveParty = () => {
        setParties((prev) => {
            const next = renumber(prev.filter((_, i) => i !== activeSlide));
            setActiveSlide((s) => Math.max(0, Math.min(s, next.length - 1)));
            return next;
        });
    };

    const activeParty = parties[activeSlide];
    const tabBtn = (isActive: boolean) =>
        `py-2 px-4 text-sm font-semibold rounded-lg transition-all ${isActive ? "bg-primary text-white" : "text-on-surface-variant hover:bg-surface-container-low"
        }`;

    return (
        <div
            className="bg-white p-8 rounded-xl border border-outline-variant mb-10"
            style={{ boxShadow: "0 4px 12px rgba(20, 27, 46, 0.04)" }}
        >
            <h2 className="font-document-title text-xl font-semibold mb-4">{label}</h2>

            <div className="flex gap-2 mb-4">
                <button onClick={() => setTab("type")} className={tabBtn(tab === "type")}>Type</button>
                <button onClick={() => setTab("upload")} className={tabBtn(tab === "upload")}>Upload Document</button>
                <button onClick={() => setTab("voice")} className={tabBtn(tab === "voice")}>Voice</button>
            </div>

            {tab === "type" && (
                <div className="flex gap-3 mb-4">
                    <input
                        type="text"
                        placeholder="e.g. Ram Kumar S/O Shyam Kumar, Age 35, Lucknow, UP"
                        value={manualText}
                        onChange={(e) => setManualText(e.target.value)}
                        className="flex-1 p-2 text-sm rounded-lg border border-outline-variant focus:outline-none focus:border-primary"
                    />
                    <button
                        onClick={handleManualAdd}
                        disabled={loading}
                        className="py-2 px-5 bg-primary text-white text-sm font-semibold rounded-lg hover:bg-[#0a523f] transition-all active:scale-95 disabled:opacity-40"
                    >
                        {loading ? "Adding..." : "Add"}
                    </button>
                </div>
            )}

            {tab === "upload" && (
                <div className="mb-4 flex items-center gap-3">
                    <input
                        type="file"
                        accept="image/*,application/pdf"
                        onChange={(e) => {
                            const file = e.target.files?.[0];
                            if (file) handleFileUpload(file);
                        }}
                        className="text-sm text-on-surface-variant"
                    />
                    {loading && <span className="text-sm text-outline">Processing...</span>}
                </div>
            )}

            {tab === "voice" && (
                <div className="mb-4 flex items-center gap-3">
                    <button
                        onClick={recording ? stopRecording : startRecording}
                        className={`py-2 px-5 text-sm font-semibold rounded-lg transition-all active:scale-95 ${recording ? "bg-error text-white hover:bg-[#93000a]" : "bg-primary text-white hover:bg-[#0a523f]"
                            }`}
                    >
                        {recording ? "Stop Recording" : "Record"}
                    </button>
                    {loading && <span className="text-sm text-outline">Processing...</span>}
                </div>
            )}

            {error && <div className="text-error text-sm mb-4">{error}</div>}

            {parties.length > 0 && activeParty && (
                <div className="bg-surface-container-low rounded-lg p-5">
                    <div className="flex items-center justify-between mb-4">
                        <button
                            onClick={() => setActiveSlide((s) => Math.max(0, s - 1))}
                            disabled={activeSlide === 0}
                            className="text-primary disabled:opacity-30 font-semibold"
                        >
                            ◀
                        </button>
                        <span className="text-sm font-semibold text-on-surface-variant">
                            Party {activeSlide + 1} of {parties.length}
                        </span>
                        <button
                            onClick={() => setActiveSlide((s) => Math.min(parties.length - 1, s + 1))}
                            disabled={activeSlide === parties.length - 1}
                            className="text-primary disabled:opacity-30 font-semibold"
                        >
                            ▶
                        </button>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {[
                            { label: "Full Name", field: "full_name" as const, type: "text" },
                            { label: "Relation Name", field: "relation_name" as const, type: "text" },
                            { label: "Age", field: "age" as const, type: "number" },
                            { label: "Address", field: "address" as const, type: "text" },
                            { label: "State", field: "state" as const, type: "text" },
                            { label: "Country", field: "country" as const, type: "text" },
                        ].map(({ label, field, type }) => (
                            <label key={field} className="text-xs font-semibold uppercase text-on-surface-variant">
                                {label}
                                <input
                                    type={type}
                                    value={(activeParty[field] as any) ?? ""}
                                    onChange={(e) =>
                                        updateActiveParty(field, type === "number" ? (e.target.value ? Number(e.target.value) : null) : e.target.value)
                                    }
                                    className="w-full mt-1 p-2 text-sm rounded-lg border border-outline-variant bg-white focus:outline-none focus:border-primary font-normal"
                                />
                            </label>
                        ))}
                        <label className="text-xs font-semibold uppercase text-on-surface-variant">
                            Relation
                            <select
                                value={activeParty.relation_type}
                                onChange={(e) => updateActiveParty("relation_type", e.target.value)}
                                className="w-full mt-1 p-2 text-sm rounded-lg border border-outline-variant bg-white focus:outline-none focus:border-primary font-normal"
                            >
                                <option value="">--</option>
                                <option value="S/O">S/O</option>
                                <option value="D/O">D/O</option>
                                <option value="W/O">W/O</option>
                                <option value="C/O">C/O</option>
                            </select>
                        </label>
                    </div>

                    <button
                        onClick={removeActiveParty}
                        className="mt-4 text-error text-sm font-semibold hover:underline"
                    >
                        Remove this party
                    </button>
                </div>
            )}
        </div>
    );
}

export default function PartiesPage() {
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
                        Petitioner-Opponent Party Extractor
                    </h1>
                    <p className="font-body-lg text-on-surface-variant mb-10">
                        Type, upload a document, or dictate party details — for both sides of the case.
                    </p>

                    <PartyListEditor label="Petitioner / Appellant / Complainant" />
                    <PartyListEditor label="Respondent / Opposite Party" />
                </main>
            </div>
        </div>
    );
}