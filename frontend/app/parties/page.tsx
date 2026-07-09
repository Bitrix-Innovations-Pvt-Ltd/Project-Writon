"use client";

import { useState, useRef } from "react";

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

const emptyParty = (serial_no: number): Party => ({
    serial_no,
    full_name: "",
    relation_type: "",
    relation_name: "",
    age: null,
    address: "",
    state: "",
    country: "India",
    raw_text: "",
});

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

    const renumber = (list: Party[]) =>
        list.map((p, i) => ({ ...p, serial_no: i + 1 }));

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
        setParties((prev) =>
            prev.map((p, i) => (i === activeSlide ? { ...p, [field]: value } : p))
        );
    };

    const removeActiveParty = () => {
        setParties((prev) => {
            const next = renumber(prev.filter((_, i) => i !== activeSlide));
            setActiveSlide((s) => Math.max(0, Math.min(s, next.length - 1)));
            return next;
        });
    };

    const activeParty = parties[activeSlide];

    return (
        <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 16, marginBottom: 24 }}>
            <h3>{label}</h3>

            <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                <button onClick={() => setTab("type")} style={{ fontWeight: tab === "type" ? "bold" : "normal" }}>
                    Type
                </button>
                <button onClick={() => setTab("upload")} style={{ fontWeight: tab === "upload" ? "bold" : "normal" }}>
                    Upload Document
                </button>
                <button onClick={() => setTab("voice")} style={{ fontWeight: tab === "voice" ? "bold" : "normal" }}>
                    Voice
                </button>
            </div>

            {tab === "type" && (
                <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                    <input
                        type="text"
                        placeholder="e.g. Ram Kumar S/O Shyam Kumar, Age 35, Lucknow, UP"
                        value={manualText}
                        onChange={(e) => setManualText(e.target.value)}
                        style={{ flex: 1, padding: 6 }}
                    />
                    <button onClick={handleManualAdd} disabled={loading}>
                        {loading ? "Adding..." : "Add"}
                    </button>
                </div>
            )}

            {tab === "upload" && (
                <div style={{ marginBottom: 12 }}>
                    <input
                        type="file"
                        accept="image/*,application/pdf"
                        onChange={(e) => {
                            const file = e.target.files?.[0];
                            if (file) handleFileUpload(file);
                        }}
                    />
                    {loading && <span style={{ marginLeft: 8, color: "gray" }}>Processing...</span>}
                </div>
            )}

            {tab === "voice" && (
                <div style={{ marginBottom: 12 }}>
                    <button onClick={recording ? stopRecording : startRecording}>
                        {recording ? "Stop Recording" : "Record"}
                    </button>
                    {loading && <span style={{ marginLeft: 8, color: "gray" }}>Processing...</span>}
                </div>
            )}

            {error && <div style={{ color: "red", marginBottom: 12 }}>{error}</div>}

            {parties.length > 0 && activeParty && (
                <div style={{ background: "#f5f5f5", padding: 12, borderRadius: 6 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                        <button onClick={() => setActiveSlide((s) => Math.max(0, s - 1))} disabled={activeSlide === 0}>
                            ◀
                        </button>
                        <span>Party {activeSlide + 1} of {parties.length}</span>
                        <button
                            onClick={() => setActiveSlide((s) => Math.min(parties.length - 1, s + 1))}
                            disabled={activeSlide === parties.length - 1}
                        >
                            ▶
                        </button>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                        <label>
                            Full Name
                            <input
                                value={activeParty.full_name}
                                onChange={(e) => updateActiveParty("full_name", e.target.value)}
                                style={{ width: "100%" }}
                            />
                        </label>
                        <label>
                            Relation
                            <select
                                value={activeParty.relation_type}
                                onChange={(e) => updateActiveParty("relation_type", e.target.value)}
                                style={{ width: "100%" }}
                            >
                                <option value="">--</option>
                                <option value="S/O">S/O</option>
                                <option value="D/O">D/O</option>
                                <option value="W/O">W/O</option>
                                <option value="C/O">C/O</option>
                            </select>
                        </label>
                        <label>
                            Relation Name
                            <input
                                value={activeParty.relation_name}
                                onChange={(e) => updateActiveParty("relation_name", e.target.value)}
                                style={{ width: "100%" }}
                            />
                        </label>
                        <label>
                            Age
                            <input
                                type="number"
                                value={activeParty.age ?? ""}
                                onChange={(e) => updateActiveParty("age", e.target.value ? Number(e.target.value) : null)}
                                style={{ width: "100%" }}
                            />
                        </label>
                        <label>
                            Address
                            <input
                                value={activeParty.address}
                                onChange={(e) => updateActiveParty("address", e.target.value)}
                                style={{ width: "100%" }}
                            />
                        </label>
                        <label>
                            State
                            <input
                                value={activeParty.state}
                                onChange={(e) => updateActiveParty("state", e.target.value)}
                                style={{ width: "100%" }}
                            />
                        </label>
                        <label>
                            Country
                            <input
                                value={activeParty.country}
                                onChange={(e) => updateActiveParty("country", e.target.value)}
                                style={{ width: "100%" }}
                            />
                        </label>
                    </div>

                    <button onClick={removeActiveParty} style={{ marginTop: 8, color: "red" }}>
                        Remove this party
                    </button>
                </div>
            )}
        </div>
    );
}

export default function PartiesPage() {
    return (
        <div style={{ maxWidth: 900, margin: "40px auto", padding: 20, fontFamily: "sans-serif" }}>
            <h1>Petitioner-Opponent Party Extractor</h1>
            <PartyListEditor label="Petitioner / Appellant / Complainant" />
            <PartyListEditor label="Respondent / Opposite Party" />
        </div>
    );
}