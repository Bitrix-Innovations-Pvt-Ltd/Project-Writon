'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import Navbar from '@/components/shared/Navbar';

interface JudgmentDetail {
  id: number;
  title: string;
  year: number;
  case_type: string;
  summary: string;
  holding: string;
  full_text: string;
  has_pdf: boolean;
}

export default function JudgmentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params?.id;

  const [judgment, setJudgment] = useState<JudgmentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isDownloading, setIsDownloading] = useState(false);
  const [activeTab, setActiveTab] = useState<'summary' | 'holding' | 'full_text'>('summary');
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);

  // Formatting helper to highlight key structure like "List of Acts", "Case Arising From", etc.
  const formatStructuredText = (text: string) => {
    if (!text) return null;
    return text.split('\n').map((line, idx) => {
      // Highlight specific headings
      if (
        line.trim() === 'List of Acts' ||
        line.trim() === 'List of Keywords' ||
        line.trim() === 'Case Arising From' ||
        line.trim() === 'Issue for Consideration' ||
        line.trim() === 'Headnotes+'
      ) {
        return (
          <div key={idx} className="font-bold text-primary mt-4 mb-2 text-base">
            {line}
          </div>
        );
      }
      // Bold important acts like Constitution of India, IPC, etc.
      let formattedLine = line;
      const acts = ['Constitution of India', 'Indian Penal Code', 'Code of Criminal Procedure'];
      acts.forEach((act) => {
        if (formattedLine.includes(act)) {
          formattedLine = formattedLine.replace(
            new RegExp(act, 'g'),
            `**${act}**`
          );
        }
      });
      // Handle the bolding we just added
      const parts = formattedLine.split(/\*\*(.*?)\*\*/g);
      
      return (
        <p key={idx} className="mb-2 leading-relaxed">
          {parts.map((part, pIdx) =>
            pIdx % 2 === 1 ? (
              <span key={pIdx} className="font-bold text-[#0a523f] bg-primary/5 px-1 rounded">
                {part}
              </span>
            ) : (
              part
            )
          )}
        </p>
      );
    });
  };

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    fetch(`http://localhost:8000/api/judgment/${id}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        setJudgment(data);
        setLoading(false);
      })
      .catch((err) => {
        setError('Could not load judgment. Please ensure the backend is running.');
        setLoading(false);
      });
  }, [id]);

  const handleDownload = async () => {
    if (!id || isDownloading) return;
    setIsDownloading(true);
    try {
      const res = await fetch(`http://localhost:8000/api/judgment/${id}/download`);
      if (!res.ok) throw new Error('Download failed');
      const data = await res.json();
      if (data.url) {
        window.open(data.url, '_blank');
      }
    } catch {
      alert('PDF download failed. The file may not be available.');
    } finally {
      setIsDownloading(false);
    }
  };

  // Fetch PDF URL for preview if available and tab is full_text
  useEffect(() => {
    if (activeTab === 'full_text' && judgment?.has_pdf && !pdfUrl) {
      fetch(`http://localhost:8000/api/judgment/${id}/download`)
        .then((res) => {
          if (!res.ok) throw new Error('Failed to get PDF URL');
          return res.json();
        })
        .then((data) => {
          if (data.url) setPdfUrl(data.url);
        })
        .catch((err) => console.error('PDF preview error:', err));
    }
  }, [activeTab, judgment, id, pdfUrl]);

  return (
    <div className="font-body-md text-on-surface bg-[#FAF9F6] min-h-screen relative selection:bg-primary-fixed selection:text-on-primary-fixed">
      {/* Paper texture overlay */}
      <div
        className="fixed inset-0 z-0 pointer-events-none opacity-[0.03]"
        style={{ backgroundImage: 'url("https://www.transparenttextures.com/patterns/parchment.png")' }}
      />

      <div className="relative z-10 flex flex-col min-h-screen">
        <Navbar />

        <main className="flex-1 max-w-[960px] mx-auto w-full px-4 md:px-10 py-10">
          {/* Back link */}
          <Link
            href="/search"
            className="inline-flex items-center gap-1.5 text-sm font-semibold text-on-surface-variant hover:text-primary transition-colors mb-8 group"
          >
            <span className="material-symbols-outlined text-[18px] group-hover:-translate-x-1 transition-transform">
              arrow_back
            </span>
            Back to Precedents
          </Link>

          {/* Loading State */}
          {loading && (
            <div className="py-32 text-center">
              <span className="material-symbols-outlined animate-spin text-5xl text-primary mb-4">autorenew</span>
              <p className="text-on-surface-variant font-body-lg text-lg">Loading judgment...</p>
            </div>
          )}

          {/* Error State */}
          {error && (
            <div className="py-32 text-center">
              <span className="material-symbols-outlined text-5xl text-error mb-4">error</span>
              <p className="text-error font-body-lg text-lg">{error}</p>
            </div>
          )}

          {/* Judgment Content */}
          {!loading && !error && judgment && (
            <article className="space-y-8 animate-fade-slide-up">
              {/* Header Card */}
              <div className="bg-white rounded-2xl border border-outline-variant shadow-sm p-8 md:p-10">
                <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
                  <div className="flex flex-wrap gap-2">
                    <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-bold bg-surface-container-high text-primary tracking-wide uppercase">
                      SC · {judgment.year || 'N/A'}
                    </span>
                    <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-bold bg-primary-fixed text-on-primary-fixed tracking-wide uppercase">
                      {judgment.case_type || 'General'}
                    </span>
                  </div>

                  {/* Download PDF button */}
                  <button
                    id="download-pdf-btn"
                    onClick={handleDownload}
                    disabled={!judgment.has_pdf || isDownloading}
                    title={!judgment.has_pdf ? 'PDF not available for this judgment' : 'Download original PDF from S3'}
                    className={`inline-flex items-center gap-2 px-5 py-2.5 rounded-lg font-label-md text-sm font-bold transition-all duration-300 ${
                      judgment.has_pdf
                        ? 'bg-primary text-white hover:bg-[#004131] hover:-translate-y-0.5 hover:shadow-[0_6px_16px_rgba(14,107,82,0.3)] active:scale-95'
                        : 'bg-surface-container-high text-outline cursor-not-allowed opacity-60'
                    }`}
                  >
                    {isDownloading ? (
                      <span className="material-symbols-outlined text-[18px] animate-spin">autorenew</span>
                    ) : (
                      <span className="material-symbols-outlined text-[18px]">download</span>
                    )}
                    {isDownloading ? 'Generating link...' : 'Download PDF'}
                  </button>
                </div>

                <h1 className="font-display-lg text-2xl md:text-3xl font-bold text-on-background leading-snug">
                  {judgment.title}
                </h1>
              </div>

              {/* Tab Navigation */}
              <div className="bg-white rounded-2xl border border-outline-variant shadow-sm overflow-hidden">
                <div className="flex border-b border-outline-variant">
                  {[
                    { key: 'summary', label: 'Summary', icon: 'summarize' },
                    { key: 'holding', label: 'Holding', icon: 'gavel' },
                    { key: 'full_text', label: 'Full Text', icon: 'article' },
                  ].map(({ key, label, icon }) => (
                    <button
                      key={key}
                      id={`tab-${key}`}
                      onClick={() => setActiveTab(key as typeof activeTab)}
                      className={`flex-1 flex items-center justify-center gap-2 py-4 px-3 text-sm font-semibold transition-all duration-200 border-b-2 ${
                        activeTab === key
                          ? 'border-primary text-primary bg-primary/5'
                          : 'border-transparent text-on-surface-variant hover:text-on-background hover:bg-surface-container-low'
                      }`}
                    >
                      <span className="material-symbols-outlined text-[18px]">{icon}</span>
                      <span className="hidden sm:inline">{label}</span>
                    </button>
                  ))}
                </div>

                {/* Tab Content */}
                <div className="p-8 md:p-10">
                  {activeTab === 'summary' && (
                    <div>
                      <h2 className="font-display-lg text-lg font-bold text-on-background mb-4 flex items-center gap-2">
                        <span className="material-symbols-outlined text-primary text-xl">summarize</span>
                        Case Summary
                      </h2>
                      <div className="text-on-surface text-[15px]">
                        {judgment.summary ? formatStructuredText(judgment.summary) : 'No summary available for this judgment.'}
                      </div>
                    </div>
                  )}

                  {activeTab === 'holding' && (
                    <div>
                      <h2 className="font-display-lg text-lg font-bold text-on-background mb-4 flex items-center gap-2">
                        <span className="material-symbols-outlined text-primary text-xl">gavel</span>
                        Court&apos;s Holding
                      </h2>
                      <div className="relative pl-6 border-l-4 border-primary/30">
                        <div className="text-on-surface text-[15px] italic">
                          {judgment.holding ? formatStructuredText(judgment.holding) : 'Holding not available for this judgment.'}
                        </div>
                      </div>
                    </div>
                  )}

                  {activeTab === 'full_text' && (
                    <div>
                      <h2 className="font-display-lg text-lg font-bold text-on-background mb-4 flex items-center gap-2">
                        <span className="material-symbols-outlined text-primary text-xl">article</span>
                        Full Judgment PDF
                      </h2>
                      {pdfUrl ? (
                        <div className="w-full h-[800px] border border-outline-variant rounded-xl overflow-hidden bg-surface-container-low">
                          <iframe src={pdfUrl} className="w-full h-full" title="PDF Preview" />
                        </div>
                      ) : judgment.has_pdf ? (
                        <div className="flex flex-col items-center justify-center py-20 text-on-surface-variant">
                          <span className="material-symbols-outlined animate-spin text-4xl mb-4 text-primary">autorenew</span>
                          <p>Loading PDF viewer...</p>
                        </div>
                      ) : judgment.full_text ? (
                        <div className="prose prose-sm max-w-none">
                          <pre className="whitespace-pre-wrap font-body-md text-[14px] text-on-surface leading-relaxed bg-surface-container-low rounded-xl p-6 border border-outline-variant overflow-auto max-h-[600px]">
                            {judgment.full_text}
                          </pre>
                        </div>
                      ) : (
                        <div className="text-center py-12 text-on-surface-variant">
                          <span className="material-symbols-outlined text-4xl mb-2 text-outline">description</span>
                          <p>Full text not available. Download the PDF for the complete judgment.</p>
                          {judgment.has_pdf && (
                            <button
                              onClick={handleDownload}
                              disabled={isDownloading}
                              className="mt-4 inline-flex items-center gap-2 px-5 py-2.5 rounded-lg font-label-md text-sm font-bold bg-primary text-white hover:bg-[#004131] transition-all duration-300 active:scale-95"
                            >
                              <span className="material-symbols-outlined text-[18px]">download</span>
                              Download PDF
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* Binding Info Footer */}
              <div className="bg-white rounded-2xl border border-outline-variant shadow-sm p-6 flex items-center gap-4">
                <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                  <span className="material-symbols-outlined text-primary text-xl">account_balance</span>
                </div>
                <div>
                  <p className="font-semibold text-sm text-on-background">Binding Applicability</p>
                  <p className="text-xs text-on-surface-variant mt-0.5">
                    {judgment.case_type?.includes('Constitutional')
                      ? 'Binding on all High Courts and District Courts across India.'
                      : 'Binding on relevant subordinate courts in applicable jurisdictions.'}
                  </p>
                </div>
              </div>
            </article>
          )}
        </main>
      </div>
    </div>
  );
}
