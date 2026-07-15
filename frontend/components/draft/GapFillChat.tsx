'use client';

import { useState, useEffect, useRef } from 'react';

interface GapFillChatProps {
  draftId: number;
  documentTypeKey: string;
  formData: any;
  onComplete: (summary: any) => void;
}

export default function GapFillChat({ draftId, documentTypeKey, formData, onComplete }: GapFillChatProps) {
  const [messages, setMessages] = useState<any[]>([]);
  const [currentGap, setCurrentGap] = useState<any>(null);
  const [inputValue, setInputValue] = useState("");
  const [loading, setLoading] = useState(true);
  const [activeDraftId, setActiveDraftId] = useState<number | null>(isNaN(draftId) ? null : draftId);
  const [updatedFormData, setUpdatedFormData] = useState<any>(formData);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const initialized = useRef(false);

  useEffect(() => {
    if (!initialized.current) {
      initialized.current = true;
      startGapFill();
    }
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  async function startGapFill() {
    try {
      const res = await fetch(`http://localhost:8000/api/v1/gapfill/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          draft_id: activeDraftId,
          document_type_key: documentTypeKey,
          form_data: formData,
        })
      });
      const data = await res.json();
      if (data.draft_id) setActiveDraftId(data.draft_id);
      if (data.updated_form_data) setUpdatedFormData(data.updated_form_data);
      handleResponse(data);
    } catch (e) {
      console.error("Failed to start gapfill", e);
      // Failsafe: if backend fails, just complete
      onComplete({ added: [], skipped: [] }, updatedFormData, activeDraftId);
    }
  }

  function handleResponse(data: any) {
    if (data.phase === "complete") {
      onComplete(data.summary, data.updated_form_data || updatedFormData, data.draft_id || activeDraftId);
      return;
    }
    setCurrentGap(data);
    setMessages(prev => [...prev, { role: "bot", text: data.question, whyRelevant: data.why_relevant }]);
    setLoading(false);
  }

  async function submitAnswer(answer: string | null, skipped = false) {
    if (!skipped && !answer?.trim()) return;

    setMessages(prev => [...prev, { role: "user", text: skipped ? "Skipped" : answer }]);
    setLoading(true);
    setInputValue("");
    
    try {
      const res = await fetch(`http://localhost:8000/api/v1/gapfill/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          draft_id: activeDraftId,
          field: currentGap.gap?.field_key || currentGap.gap?.field || currentGap.question,
          gap_type: currentGap.phase,
          answer: skipped ? null : answer,
          skipped,
        })
      });
      const data = await res.json();
      if (data.updated_form_data) setUpdatedFormData(data.updated_form_data);
      handleResponse(data);
    } catch (e) {
      console.error("Failed to submit answer", e);
      // Failsafe
      onComplete({ added: [], skipped: [] }, updatedFormData, activeDraftId);
    }
  }

  return (
    <div className="flex flex-col h-[500px] border border-surface-border rounded-xl bg-surface-container overflow-hidden shadow-sm">
      {/* Header */}
      <div className="bg-surface p-4 border-b border-surface-border flex justify-between items-center">
        <div>
          <h3 className="text-lg font-semibold text-on-surface">Legal Assistant</h3>
          <p className="text-sm text-on-surface-variant">Let's clarify a few details to strengthen your draft.</p>
        </div>
        {currentGap && currentGap.remaining_count !== undefined && (
          <span className="text-xs bg-primary/10 text-primary px-2 py-1 rounded-full font-medium">
            {currentGap.remaining_count} remaining
          </span>
        )}
      </div>

      {/* Chat Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[80%] rounded-2xl p-4 shadow-sm ${
              m.role === 'user' 
                ? 'bg-primary text-on-primary rounded-tr-sm' 
                : 'bg-surface text-on-surface border border-surface-border rounded-tl-sm'
            }`}>
              <p className="text-sm">{m.text}</p>
              {m.whyRelevant && (
                <div className="mt-2 pt-2 border-t border-surface-border/50 text-xs text-on-surface-variant opacity-80">
                  <span className="font-semibold block mb-1">Why this matters:</span>
                  {m.whyRelevant}
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-surface border border-surface-border rounded-2xl rounded-tl-sm p-4 flex space-x-2">
              <div className="w-2 h-2 rounded-full bg-primary animate-bounce"></div>
              <div className="w-2 h-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: '0.2s' }}></div>
              <div className="w-2 h-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: '0.4s' }}></div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      {!loading && currentGap && (
        <div className="p-4 bg-surface border-t border-surface-border">
          <div className="flex space-x-2">
            <input
              type="text"
              value={inputValue}
              onChange={e => setInputValue(e.target.value)}
              onKeyDown={e => e.key === "Enter" && submitAnswer(inputValue)}
              placeholder="Type your answer here..."
              className="flex-1 bg-surface-container border border-surface-border rounded-xl px-4 py-2 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent text-on-surface"
              autoFocus
            />
            <button 
              onClick={() => submitAnswer(inputValue)}
              disabled={!inputValue.trim()}
              className="bg-primary text-on-primary px-6 py-2 rounded-xl font-medium hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Send
            </button>
            {(currentGap.gap?.priority !== "required" || currentGap.phase === 'context') && (
              <button 
                className="px-4 py-2 text-on-surface-variant hover:text-on-surface hover:bg-surface-container rounded-xl transition-colors font-medium text-sm"
                onClick={() => submitAnswer(null, true)}
              >
                Skip
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
