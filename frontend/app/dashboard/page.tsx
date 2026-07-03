'use client';

import Navbar from "@/components/shared/Navbar";
import Link from "next/link";
import { useRef, useState, useCallback } from "react";

export default function DashboardPage() {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [startX, setStartX] = useState(0);
  const [scrollLeft, setScrollLeft] = useState(0);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (!scrollContainerRef.current) return;
    setIsDragging(true);
    setStartX(e.pageX - scrollContainerRef.current.offsetLeft);
    setScrollLeft(scrollContainerRef.current.scrollLeft);
  }, []);

  const handleMouseLeave = useCallback(() => {
    setIsDragging(false);
  }, []);

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isDragging || !scrollContainerRef.current) return;
    e.preventDefault();
    const x = e.pageX - scrollContainerRef.current.offsetLeft;
    const walk = (x - startX) * 2;
    scrollContainerRef.current.scrollLeft = scrollLeft - walk;
  }, [isDragging, startX, scrollLeft]);

  return (
    <div className="min-h-screen bg-surface flex flex-col font-body-md text-body-md selection:bg-primary-fixed selection:text-on-primary-fixed">
      <Navbar />
      
      <main className="flex-grow flex flex-col relative" style={{ backgroundImage: 'url("https://www.transparenttextures.com/patterns/parchment.png")', backgroundColor: 'rgba(250, 248, 255, 0.98)', backgroundBlendMode: 'overlay' }}>
        
        {/* Hero Section */}
        <section className="relative pt-24 pb-16 px-4 md:px-10 overflow-hidden">
          <div className="max-w-[850px] mx-auto text-center space-y-8 animate-fade-slide-up">
            {/* Eyebrow */}
            <div className="inline-flex items-center px-4 py-1.5 rounded-full font-label-sm text-label-sm tracking-widest uppercase font-bold border border-primary/20 bg-primary/5 text-primary">
              AI-POWERED · INDIAN JUDICIARY · COURT-READY
            </div>
            
            {/* Headline */}
            <h1 className="font-display-lg text-5xl md:text-[64px] md:leading-[1.1] text-on-background font-bold">
              Draft Legal Documents <span className="text-[#0a523f] italic">10×</span> Faster
            </h1>
            
            {/* Subhead */}
            <p className="font-body-lg text-lg text-on-surface-variant max-w-2xl mx-auto leading-relaxed">
              AI drafts petitions, appeals, and legal notices — grounded in 23,840+ Supreme Court precedents for unmatched authority and accuracy.
            </p>
            
            {/* Hero CTAs */}
            <div className="flex flex-col sm:flex-row items-center justify-center gap-4 pt-4">
              <Link 
                href="/draft/new" 
                className="w-full sm:w-auto px-8 py-4 rounded-lg bg-primary text-white font-label-md text-sm font-bold flex items-center justify-center gap-2 hover:bg-[#004131] hover:-translate-y-1 hover:shadow-[0_8px_20px_rgba(14,107,82,0.4)] transition-all duration-300 active:scale-95"
              >
                Start Drafting Free <span className="material-symbols-outlined">arrow_forward</span>
              </Link>
              <button className="w-full sm:w-auto px-8 py-4 rounded-lg border-2 border-outline-variant bg-white text-on-background font-label-md text-sm font-bold hover:border-primary hover:text-primary hover:-translate-y-1 hover:shadow-md transition-all duration-300 active:scale-95">
                Watch Demo
              </button>
            </div>
          </div>
          
          {/* Document Type Scroll */}
          <div className="mt-16 relative w-full overflow-hidden animate-fade-slide-up" style={{ animationDelay: '100ms' }}>
            <div 
              ref={scrollContainerRef}
              onMouseDown={handleMouseDown}
              onMouseLeave={handleMouseLeave}
              onMouseUp={handleMouseUp}
              onMouseMove={handleMouseMove}
              className={`flex gap-4 overflow-x-auto no-scrollbar px-4 md:px-10 py-6 scroll-smooth select-none ${isDragging ? 'cursor-grabbing' : 'cursor-grab'}`}
              style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
            >
              {[
                "Writ Petition", 
                "Criminal Appeal", 
                "Civil Revision", 
                "Special Leave Petition", 
                "Legal Notice", 
                "Consumer Complaint", 
                "Quashing Petition", 
                "Bail Application"
              ].map((doc, i) => (
                <div key={i} className="flex-none px-6 py-3 rounded-full border-2 border-outline-variant bg-white text-on-surface font-label-md text-sm font-bold hover:border-primary hover:text-primary hover:-translate-y-1 hover:shadow-[0_4px_12px_rgba(14,107,82,0.15)] transition-all duration-300">
                  {doc}
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Feature Grid Section */}
        <section className="py-24 px-4 md:px-10 bg-white border-y border-outline-variant">
          <div className="max-w-[1280px] mx-auto">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
              {/* Feature 1 */}
              <div className="p-8 rounded-xl border-2 border-outline-variant hover:border-primary transition-all duration-300 hover:-translate-y-2 hover:shadow-xl group bg-white">
                <div className="w-14 h-14 rounded-full bg-primary/10 flex items-center justify-center mb-6 group-hover:scale-110 transition-transform duration-300">
                  <span className="text-2xl">⚖️</span>
                </div>
                <h3 className="font-display-lg text-2xl font-bold mb-4 text-on-background">AI Document Drafting</h3>
                <p className="text-on-surface-variant text-sm leading-relaxed">Intelligent document generator that understands legal context and structures documents professionally.</p>
              </div>
              {/* Feature 2 */}
              <div className="p-8 rounded-xl border-2 border-outline-variant hover:border-primary transition-all duration-300 hover:-translate-y-2 hover:shadow-xl group bg-white">
                <div className="w-14 h-14 rounded-full bg-primary/10 flex items-center justify-center mb-6 group-hover:scale-110 transition-transform duration-300">
                  <span className="text-2xl">📚</span>
                </div>
                <h3 className="font-display-lg text-2xl font-bold mb-4 text-on-background">23,840+ SC Precedents</h3>
                <p className="text-on-surface-variant text-sm leading-relaxed">Our AI is trained specifically on Indian Supreme Court judgments to provide relevant legal arguments.</p>
              </div>
              {/* Feature 3 */}
              <div className="p-8 rounded-xl border-2 border-outline-variant hover:border-primary transition-all duration-300 hover:-translate-y-2 hover:shadow-xl group bg-white">
                <div className="w-14 h-14 rounded-full bg-primary/10 flex items-center justify-center mb-6 group-hover:scale-110 transition-transform duration-300">
                  <span className="text-2xl">🏛️</span>
                </div>
                <h3 className="font-display-lg text-2xl font-bold mb-4 text-on-background">All Court Levels</h3>
                <p className="text-on-surface-variant text-sm leading-relaxed">Templates and logic engines designed for High Courts, District Courts, and Specialized Tribunals.</p>
              </div>
              {/* Feature 4 */}
              <div className="p-8 rounded-xl border-2 border-outline-variant hover:border-primary transition-all duration-300 hover:-translate-y-2 hover:shadow-xl group bg-white">
                <div className="w-14 h-14 rounded-full bg-primary/10 flex items-center justify-center mb-6 group-hover:scale-110 transition-transform duration-300">
                  <span className="text-2xl">🇮🇳</span>
                </div>
                <h3 className="font-display-lg text-2xl font-bold mb-4 text-on-background">Built for India</h3>
                <p className="text-on-surface-variant text-sm leading-relaxed">Localized formatting and procedural compliance for the unique requirements of Indian legal practice.</p>
              </div>
            </div>
          </div>
        </section>

        {/* Asymmetric Visual Showcase */}
        <section className="py-32 px-4 md:px-10 overflow-hidden bg-[#FAF9F6]">
          <div className="max-w-[1280px] mx-auto flex flex-col lg:flex-row items-center gap-16">
            <div className="flex-1 space-y-8 animate-fade-slide-up">
              <h2 className="font-display-lg text-4xl md:text-[48px] leading-tight font-bold text-on-background">Precision Drafting with Judicial Context</h2>
              <p className="font-body-lg text-lg text-on-surface-variant leading-relaxed">
                Unlike generic AI, Writon is fine-tuned on the intricacies of Indian law. Every draft produced undergoes a context-check against the latest circulars and landmark rulings from 1950 to 2024.
              </p>
              <ul className="space-y-5">
                <li className="flex items-center gap-4">
                  <span className="material-symbols-outlined text-[#0a523f] text-xl" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                  <span className="font-semibold text-base">Automatic case citation matching</span>
                </li>
                <li className="flex items-center gap-4">
                  <span className="material-symbols-outlined text-[#0a523f] text-xl" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                  <span className="font-semibold text-base">Procedural compliance for 28 High Courts</span>
                </li>
                <li className="flex items-center gap-4">
                  <span className="material-symbols-outlined text-[#0a523f] text-xl" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                  <span className="font-semibold text-base">Real-time collaborative editing</span>
                </li>
              </ul>
            </div>
            <div className="flex-1 relative w-full max-w-[600px] lg:max-w-none">
              <div className="w-full h-[500px] bg-white rounded-2xl border-2 border-outline-variant shadow-2xl overflow-hidden relative group">
                <img className="w-full h-full object-cover transition-transform duration-700 group-hover:scale-105" alt="Legal drafting AI dashboard" src="https://lh3.googleusercontent.com/aida-public/AB6AXuChLlaRvGQyMfoFyCJzo0fq9xlWjushHx6L-b7V3xtdyHd4OLJyJjp-INqugqNMyNsG35g08XcCfpa5n-8H8ZOwaVgOzT6Vc09JbTk5IU-GC9dOjHA3jAaHx-VQs7f0nqnFNk_y4FywUFNMHm3d3DSW0G8ryiX5IyliJ_ldemOQpnohq7I1G0FmPyol-L6ctD8TaMLEfLIv7MfIcCI1kHe30zrH_VJFuHQ8LbZka39FG_fZ8wUwlfNExQ" />
                <div className="absolute inset-0 bg-gradient-to-tr from-primary/20 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500"></div>
              </div>
              {/* Floating Stat Card */}
              <div className="absolute -bottom-8 -left-8 md:-left-12 bg-[#293044] p-8 rounded-2xl shadow-2xl border border-outline-variant animate-bounce-subtle z-10">
                <div className="text-primary-fixed font-display-lg text-4xl md:text-5xl font-bold mb-1">99.2%</div>
                <div className="text-white font-bold text-xs tracking-widest uppercase">Draft Accuracy</div>
              </div>
            </div>
          </div>
        </section>

        {/* Bottom CTA */}
        <section className="py-32 px-4 md:px-10 bg-white">
          <div className="max-w-[1280px] mx-auto">
            <div className="bg-[#293044] rounded-[32px] p-12 md:p-24 text-center relative overflow-hidden group shadow-2xl">
              <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-primary/20 rounded-full blur-[100px] -mr-48 -mt-48 transition-all duration-700 group-hover:bg-primary/30 group-hover:scale-110"></div>
              <div className="absolute bottom-0 left-0 w-[300px] h-[300px] bg-secondary-fixed/10 rounded-full blur-[80px] -ml-24 -mb-24"></div>
              
              <div className="relative z-10 space-y-10">
                <h2 className="font-display-lg text-4xl md:text-6xl text-white font-bold">Ready to draft your first document?</h2>
                <p className="text-surface-variant text-lg max-w-xl mx-auto leading-relaxed">
                  Join over 5,000+ advocates across India streamlining their practice with Writon.
                </p>
                <Link href="/draft/new" className="inline-flex items-center gap-3 px-12 py-5 rounded-full bg-primary text-white font-bold text-lg hover:bg-[#0a523f] hover:-translate-y-1 transition-all duration-300 shadow-[0_0_40px_rgba(14,107,82,0.4)] active:scale-95 group-hover:shadow-[0_0_60px_rgba(14,107,82,0.6)]">
                  Open the Drafting Wizard <span className="material-symbols-outlined text-2xl animate-pulse">magic_button</span>
                </Link>
              </div>
            </div>
          </div>
        </section>

      </main>
    </div>
  );
}
