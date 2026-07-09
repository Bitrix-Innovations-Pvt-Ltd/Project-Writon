'use client';

import Navbar from "@/components/shared/Navbar";
import Link from "next/link";

export default function Home() {
  return (
    <div className="font-body-md text-on-surface bg-[#FAF9F6] antialiased min-h-screen flex flex-col selection:bg-primary-fixed selection:text-on-primary-fixed">
      {/* Global Navbar handles auth state and routing */}
      <Navbar />

      <main className="flex-grow">
        {/* Immersive Hero Section */}
        <section className="bg-white overflow-hidden relative">
          {/* Subtle grid pattern background for the hero */}
          <div className="absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI0MCIgaGVpZ2h0PSI0MCI+CjxwYXRoIGQ9Ik0wIDBoNDB2NDBIMHoiIGZpbGw9Im5vbmUiLz4KPHBhdGggZD0iTTAgMGg0MHYxSDB6IiBmaWxsPSIjZjJmM2ZmIiBmaWxsLW9wYWNpdHk9IjEiLz4KPHBhdGggZD0iTTAgMGgxdjQwSDB6IiBmaWxsPSIjZjJmM2ZmIiBmaWxsLW9wYWNpdHk9IjEiLz4KPC9zdmc+')] opacity-60"></div>
          
          <div className="max-w-[1280px] mx-auto px-4 md:px-10 py-16 md:py-24 relative z-10">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
              <div className="flex flex-col text-left animate-fade-slide-up">
                <span className="text-primary font-bold text-xs uppercase tracking-widest bg-primary/10 px-4 py-1.5 rounded-full mb-6 border border-primary/20 w-max shadow-sm">
                  AI-POWERED · INDIAN JUDICIARY
                </span>
                <h1 className="font-display-lg text-5xl md:text-6xl text-on-background mb-6 leading-tight font-bold">
                  Draft Legal Documents <span className="text-[#0a523f] italic">10× Faster</span>
                </h1>
                <p className="font-body-lg text-lg text-on-surface-variant mb-10 max-w-lg leading-relaxed">
                  AI drafts petitions, appeals, and notices grounded in 23,840+ Supreme Court precedents. Precision meets efficiency for modern advocates.
                </p>
                
                <div className="flex flex-col sm:flex-row gap-4 mb-10">
                  <Link href="/dashboard" className="bg-[#0a523f] text-white px-8 py-4 rounded-lg font-bold text-sm hover:bg-primary transition-all shadow-md hover:shadow-lg active:scale-95 flex items-center justify-center gap-2">
                    Start Drafting Free <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
                  </Link>
                  <button className="border-2 border-outline-variant bg-white text-on-surface px-8 py-4 rounded-lg font-bold text-sm hover:border-primary hover:text-primary transition-all active:scale-95 flex items-center justify-center gap-2">
                    <span className="material-symbols-outlined text-[20px]" style={{ fontVariationSettings: "'FILL' 1" }}>play_circle</span> Watch Demo
                  </button>
                </div>
                
                <div className="flex items-center gap-4">
                  <div className="flex -space-x-3">
                    <img alt="Advocate" className="w-10 h-10 rounded-full border-2 border-white object-cover z-30 shadow-sm" src="https://lh3.googleusercontent.com/aida-public/AB6AXuD2DuZFqI8R5Xgaa2Oy_cj2P4K02rq3bNmaWNWGqMZ5FOlKlk84TuYVnEFhS2FXsfFMj-h1rDS60SKRp-b2qaEWIH_EeVIe9aNZH2r3A_u2x9OClQ8x7f8GoGSV43Db5DCHD9hmOGXsb8I2HSAG5_PUxytqPDQ6zQtbQdze761Quf_X8n3GGnULH7C4IvwX1hYlLLTLQ0x11mYeAtStG4vgVCtyuuxI2zMHOBQcT2CBfZyhRiMF61wMqw"/>
                    <img alt="Advocate" className="w-10 h-10 rounded-full border-2 border-white object-cover z-20 shadow-sm" src="https://lh3.googleusercontent.com/aida-public/AB6AXuD3mmXS585UHZmLipZNJmEKI1PT-TwZwKPeJmvpAisx6arX6QVrIq8YW6pGGOfbAA8svn6zwNlN_RLVGoPY6AWZHZ0KtsAlOnQzKdneeNVui9k2LZ5aFTCEp1YLOOysCrvXHh_AiHKIGHt2E-GqKiDvnhNGWtFmrMFVqrxnXu_y3sUhlamJVL28IzESIVzzfiQ_VHvSPbKT15I0ssG3od1rsOdAzHJeACd1szt7cjS9ROg6aiFEursTwA"/>
                    <img alt="Advocate" className="w-10 h-10 rounded-full border-2 border-white object-cover z-10 shadow-sm" src="https://lh3.googleusercontent.com/aida-public/AB6AXuDLX7a5yTBD19RQeC4kdye9sd8FHq1DgwfB9lt1ZzjwSq_Daxz0QpMVI6goNc-oYBvfD8szU_Ky7fS6R2j99SAo6EoZGyF0LuTpDCfJF8GJXSozHqWyEPaAtkeg1CA0VM6kx6b0hJ-CkGtz8GxRs0aC0Fqd4c9dm0US2n21TMJwwRrZ1bYrVIO0ch8hE5SY7rYNqVQRAr46peDGWLkQAzXnnLDgH1YvSZI8IaF4b1xV4AiYBPTi0uxByA"/>
                    <div className="w-10 h-10 rounded-full border-2 border-white bg-surface-container-high flex items-center justify-center text-xs font-bold text-primary shadow-sm z-0">5k+</div>
                  </div>
                  <span className="text-sm text-on-surface-variant font-semibold">Trusted by 5,000+ advocates</span>
                </div>
              </div>

              <div className="relative h-full min-h-[400px] flex items-center justify-center lg:justify-end animate-fade-slide-up" style={{ animationDelay: '200ms' }}>
                <div className="absolute w-full h-full bg-gradient-to-tr from-primary/10 to-transparent rounded-full blur-3xl -z-10"></div>
                
                {/* Floating Citation Card */}
                <div className="bg-white border border-outline-variant rounded-2xl shadow-[0_20px_40px_-15px_rgba(14,107,82,0.15)] p-8 max-w-sm relative z-10 mr-4 animate-bounce-subtle">
                  <div className="flex items-center gap-2 mb-6">
                    <span className="material-symbols-outlined text-[#0a523f] text-2xl" style={{ fontVariationSettings: "'FILL' 1" }}>gavel</span>
                    <span className="font-bold text-xs text-on-surface-variant uppercase tracking-wider">Citation Match</span>
                  </div>
                  <h3 className="font-display-lg text-[22px] font-bold text-on-background mb-4 leading-snug">Kesavananda Bharati v. State of Kerala</h3>
                  <div className="bg-surface-container-low px-3 py-2 rounded mb-6 border border-outline-variant/50 inline-block">
                    <p className="text-xs font-mono font-bold text-[#0a523f]">AIR 1973 SC 1461</p>
                  </div>
                  <p className="text-sm text-on-surface-variant mb-6 leading-relaxed italic border-l-2 border-primary/20 pl-4">
                    &quot;The Basic Structure Doctrine prevents the Parliament from altering the fundamental features of the Constitution...&quot;
                  </p>
                  <div className="flex items-center justify-between border-t border-outline-variant pt-4">
                    <span className="text-xs text-outline font-bold bg-surface-container px-2 py-1 rounded">Relevance: 99%</span>
                    <button className="text-[#0a523f] text-sm font-bold hover:underline flex items-center gap-1 group">
                      Insert Draft <span className="material-symbols-outlined text-[18px] group-hover:scale-110 transition-transform">add_circle</span>
                    </button>
                  </div>
                </div>

                {/* Secondary decorative card behind */}
                <div className="absolute bottom-10 right-0 lg:-right-8 bg-surface-container-highest border border-outline-variant rounded-xl p-6 shadow-lg opacity-80 scale-90 blur-[1px] z-0 hidden md:block">
                  <div className="w-48 h-3 bg-outline-variant/30 rounded mb-4"></div>
                  <div className="w-32 h-3 bg-outline-variant/30 rounded mb-6"></div>
                  <div className="w-full h-24 bg-white rounded border border-outline-variant/20"></div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Dynamic Statistics Row */}
        <section className="bg-[#0a523f] text-white py-16 border-y-4 border-primary">
          <div className="max-w-[1280px] mx-auto px-4 md:px-10">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-8 text-center divide-y md:divide-y-0 md:divide-x divide-white/20">
              <div className="pt-4 md:pt-0 transform hover:scale-105 transition-transform duration-300">
                <div className="font-display-lg text-5xl md:text-6xl font-bold mb-3 tracking-tight">23k+</div>
                <div className="text-primary-fixed-dim text-sm font-bold uppercase tracking-widest">Supreme Court Precedents</div>
              </div>
              <div className="pt-8 md:pt-0 transform hover:scale-105 transition-transform duration-300">
                <div className="font-display-lg text-5xl md:text-6xl font-bold mb-3 tracking-tight">28</div>
                <div className="text-primary-fixed-dim text-sm font-bold uppercase tracking-widest">High Courts Covered</div>
              </div>
              <div className="pt-8 md:pt-0 transform hover:scale-105 transition-transform duration-300">
                <div className="font-display-lg text-5xl md:text-6xl font-bold mb-3 tracking-tight">99%</div>
                <div className="text-primary-fixed-dim text-sm font-bold uppercase tracking-widest">Draft Accuracy Rate</div>
              </div>
            </div>
          </div>
        </section>

        {/* Product Deep Dive */}
        <section className="bg-[#FAF9F6] py-32">
          <div className="max-w-[1280px] mx-auto px-4 md:px-10">
            <div className="text-center mb-24 animate-fade-slide-up">
              <h2 className="font-display-lg text-4xl md:text-5xl font-bold text-on-background mb-6">Scholarly Precision, Instant Drafting</h2>
              <p className="text-lg text-on-surface-variant max-w-2xl mx-auto">Explore how Writon transforms complex legal research into court-ready documents.</p>
            </div>

            {/* Feature 1 */}
            <div className="flex flex-col lg:flex-row items-center gap-16 mb-32">
              <div className="lg:w-1/2">
                <div className="w-16 h-16 bg-primary/10 rounded-2xl flex items-center justify-center text-primary mb-8 shadow-sm">
                  <span className="material-symbols-outlined text-3xl">description</span>
                </div>
                <h3 className="font-display-lg text-3xl md:text-4xl font-bold text-on-background mb-6">Context-Aware AI Drafting</h3>
                <p className="text-lg text-on-surface-variant mb-8 leading-relaxed">
                  Simply input your case facts. Our specialized AI doesn&apos;t just fill templates; it structures arguments logically, identifying the exact legal principles applicable to your facts and formatting them according to standard court requirements.
                </p>
                <ul className="space-y-4 mb-8">
                  <li className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-[#0a523f]" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                    <span className="text-on-surface font-semibold">Generates Petitions, Appeals, and Notices</span>
                  </li>
                  <li className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-[#0a523f]" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                    <span className="text-on-surface font-semibold">Maintains formal legal tone and formatting</span>
                  </li>
                </ul>
              </div>
              <div className="lg:w-1/2 w-full group">
                <div className="bg-white border-2 border-outline-variant rounded-2xl shadow-xl overflow-hidden transition-transform duration-500 group-hover:-translate-y-2 group-hover:shadow-2xl">
                  <div className="h-12 border-b border-outline-variant bg-surface-container flex items-center px-6 gap-2">
                    <div className="w-3.5 h-3.5 rounded-full bg-error/70"></div>
                    <div className="w-3.5 h-3.5 rounded-full bg-[#f7bd48]"></div>
                    <div className="w-3.5 h-3.5 rounded-full bg-primary/70"></div>
                  </div>
                  <img alt="Document Editor Interface" className="w-full h-auto object-cover" src="https://lh3.googleusercontent.com/aida-public/AB6AXuBlVhpqaIR4NhlO2P-8b1OgxXWZd3T_0yyBO7WdP7oth3qy3XYH0UILzJMb-NEIiQGa4HyGGabQkp-qsuxq9-MELs0drpkTLQNwgDaTlU2HC9EX_XBZPn6nqRFb_zBw0HHTUxVcrOoKY64Rm3kmOM8Kpp27zneOPAN4pTQAmoDqQfYHGTKoJCy5QE9cwkL2y9OjY8fGr4hmttRLTVpmEQH7PytvhBz7gHmT9hBqA5mViIm18gjF09gJrQ"/>
                </div>
              </div>
            </div>

            {/* Feature 2 */}
            <div className="flex flex-col lg:flex-row-reverse items-center gap-16 mb-32">
              <div className="lg:w-1/2">
                <div className="w-16 h-16 bg-primary/10 rounded-2xl flex items-center justify-center text-primary mb-8 shadow-sm">
                  <span className="material-symbols-outlined text-3xl">library_books</span>
                </div>
                <h3 className="font-display-lg text-3xl md:text-4xl font-bold text-on-background mb-6">Deep Precedent Integration</h3>
                <p className="text-lg text-on-surface-variant mb-8 leading-relaxed">
                  Every claim needs backing. Writon automatically cross-references your draft against an indexed database of over 23,840 Supreme Court judgments, suggesting highly relevant citations to strengthen your arguments instantly.
                </p>
                <ul className="space-y-4 mb-8">
                  <li className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-[#0a523f]" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                    <span className="text-on-surface font-semibold">Auto-suggests relevant case laws</span>
                  </li>
                  <li className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-[#0a523f]" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                    <span className="text-on-surface font-semibold">Extracts precise ratio decidendi</span>
                  </li>
                </ul>
              </div>
              <div className="lg:w-1/2 w-full">
                <div className="bg-white border-2 border-outline-variant rounded-2xl shadow-xl overflow-hidden p-8 relative">
                  <div className="space-y-6">
                    <div className="bg-primary/5 px-6 py-5 rounded-xl border-l-4 border-primary shadow-sm hover:shadow-md transition-shadow">
                      <div className="text-xs text-[#0a523f] font-bold mb-2 tracking-widest uppercase">Suggested Citation</div>
                      <div className="font-display-lg text-lg font-bold text-on-background mb-1">Maneka Gandhi v. Union of India</div>
                      <div className="text-sm text-on-surface-variant font-medium">Right to Personal Liberty (Art. 21)</div>
                    </div>
                    <div className="bg-surface-container px-6 py-5 rounded-xl border-l-4 border-outline-variant opacity-70 hover:opacity-100 transition-opacity cursor-pointer">
                      <div className="text-xs text-outline font-bold mb-2 tracking-widest uppercase">Alternate Citation</div>
                      <div className="font-display-lg text-lg font-bold text-on-background mb-1">A.K. Gopalan v. State of Madras</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Feature 3 */}
            <div className="flex flex-col lg:flex-row items-center gap-16">
              <div className="lg:w-1/2">
                <div className="w-16 h-16 bg-primary/10 rounded-2xl flex items-center justify-center text-primary mb-8 shadow-sm">
                  <span className="material-symbols-outlined text-3xl">account_balance</span>
                </div>
                <h3 className="font-display-lg text-3xl md:text-4xl font-bold text-on-background mb-6">Adapted for All Court Levels</h3>
                <p className="text-lg text-on-surface-variant mb-8 leading-relaxed">
                  Whether you are appearing before a local tribunal, a High Court, or the Supreme Court, the formatting and linguistic tone adjust automatically to meet the specific procedural norms of the jurisdiction.
                </p>
              </div>
              <div className="lg:w-1/2 w-full">
                <div className="bg-white border-2 border-outline-variant rounded-2xl shadow-xl p-8 flex flex-col gap-4">
                  <div className="flex items-center justify-between p-5 border-2 border-primary bg-primary/5 rounded-xl shadow-sm">
                    <div className="flex items-center gap-4">
                      <span className="material-symbols-outlined text-primary text-2xl">account_balance</span>
                      <span className="font-bold text-lg text-primary">Supreme Court of India</span>
                    </div>
                    <span className="material-symbols-outlined text-primary text-xl" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                  </div>
                  <div className="flex items-center justify-between p-5 border border-outline-variant hover:border-primary/50 hover:bg-surface-container-low rounded-xl cursor-pointer transition-all">
                    <div className="flex items-center gap-4">
                      <span className="material-symbols-outlined text-outline">account_balance</span>
                      <span className="font-semibold text-on-surface-variant">Delhi High Court</span>
                    </div>
                  </div>
                  <div className="flex items-center justify-between p-5 border border-outline-variant hover:border-primary/50 hover:bg-surface-container-low rounded-xl cursor-pointer transition-all">
                    <div className="flex items-center gap-4">
                      <span className="material-symbols-outlined text-outline">account_balance</span>
                      <span className="font-semibold text-on-surface-variant">National Green Tribunal</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Case Study/Comparison Section */}
        <section className="bg-white py-24 border-y border-outline-variant">
          <div className="max-w-[1000px] mx-auto px-4 md:px-10">
            <h2 className="font-display-lg text-4xl md:text-5xl text-center font-bold text-on-background mb-16">The Writon Advantage</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
              {/* Traditional */}
              <div className="bg-[#FAF9F6] p-10 rounded-2xl border-2 border-outline-variant shadow-sm flex flex-col">
                <div className="flex items-center gap-3 mb-8 text-error">
                  <span className="material-symbols-outlined text-3xl">hourglass_empty</span>
                  <h3 className="font-display-lg text-2xl font-bold text-on-background">Traditional Drafting</h3>
                </div>
                <ul className="space-y-6 flex-grow">
                  <li className="flex items-start gap-4">
                    <span className="material-symbols-outlined text-error mt-0.5" style={{ fontVariationSettings: "'FILL' 1" }}>cancel</span>
                    <span className="text-on-surface-variant font-medium text-lg leading-snug">Hours spent manually searching for precedents</span>
                  </li>
                  <li className="flex items-start gap-4">
                    <span className="material-symbols-outlined text-error mt-0.5" style={{ fontVariationSettings: "'FILL' 1" }}>cancel</span>
                    <span className="text-on-surface-variant font-medium text-lg leading-snug">Tedious formatting adjustments per court</span>
                  </li>
                  <li className="flex items-start gap-4">
                    <span className="material-symbols-outlined text-error mt-0.5" style={{ fontVariationSettings: "'FILL' 1" }}>cancel</span>
                    <span className="text-on-surface-variant font-medium text-lg leading-snug">High risk of missing relevant, recent case laws</span>
                  </li>
                </ul>
                <div className="mt-10 pt-6 border-t-2 border-outline-variant">
                  <div className="text-sm font-bold text-on-surface-variant uppercase tracking-widest mb-1">Average Time</div>
                  <div className="font-display-lg font-bold text-3xl text-on-background">4 - 6 Hours</div>
                </div>
              </div>
              
              {/* WritOnline */}
              <div className="bg-[#0a523f] p-10 rounded-2xl shadow-2xl flex flex-col text-white relative overflow-hidden transform hover:-translate-y-1 transition-transform">
                <div className="absolute top-0 right-0 bg-[#B8860B] px-4 py-2 rounded-bl-2xl text-xs font-bold shadow-md tracking-widest">10x FASTER</div>
                <div className="flex items-center gap-3 mb-8 text-primary-fixed">
                  <span className="material-symbols-outlined text-3xl" style={{ fontVariationSettings: "'FILL' 1" }}>bolt</span>
                  <h3 className="font-display-lg text-2xl font-bold text-white">With Writon</h3>
                </div>
                <ul className="space-y-6 flex-grow">
                  <li className="flex items-start gap-4">
                    <span className="material-symbols-outlined text-primary-fixed mt-0.5" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                    <span className="text-[#dbe2fc] font-medium text-lg leading-snug">Instant retrieval of highly relevant SC precedents</span>
                  </li>
                  <li className="flex items-start gap-4">
                    <span className="material-symbols-outlined text-primary-fixed mt-0.5" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                    <span className="text-[#dbe2fc] font-medium text-lg leading-snug">Auto-formatting based on jurisdiction standards</span>
                  </li>
                  <li className="flex items-start gap-4">
                    <span className="material-symbols-outlined text-primary-fixed mt-0.5" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                    <span className="text-[#dbe2fc] font-medium text-lg leading-snug">Drafts generated with rigorous logical structure</span>
                  </li>
                </ul>
                <div className="mt-10 pt-6 border-t-2 border-white/20">
                  <div className="text-sm font-bold text-primary-fixed-dim uppercase tracking-widest mb-1">Average Time</div>
                  <div className="font-display-lg font-bold text-4xl text-primary-fixed">15 - 30 Mins</div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Testimonial Section */}
        <section className="bg-surface-container-low py-24 relative overflow-hidden">
          <div className="absolute inset-0 bg-[url('https://www.transparenttextures.com/patterns/parchment.png')] opacity-[0.03]"></div>
          <div className="max-w-4xl mx-auto px-4 md:px-10 text-center relative z-10">
            <span className="material-symbols-outlined text-6xl text-primary/20 mb-8" style={{ fontVariationSettings: "'FILL' 1" }}>format_quote</span>
            <p className="font-display-lg text-3xl md:text-4xl text-on-background mb-12 italic leading-relaxed">
              &quot;Writon has fundamentally changed how my chambers operate. The sheer accuracy of the precedents it pulls and the structure of the initial drafts save us days of tedious research.&quot;
            </p>
            <div className="flex items-center justify-center gap-6">
              <img alt="Ramesh K. Iyer" className="w-16 h-16 rounded-full border-2 border-outline-variant object-cover shadow-sm" src="https://lh3.googleusercontent.com/aida-public/AB6AXuAdUMEczIvdeAbKbK5JY2uauYphvlIxdq1H40ayE_ezXkJLmwYfEhrxIopgYLiSZD5TMA4ZAVv68gc0ruzgK5iv5qNSEQM_0yZVMEvEI5poxRs8K9sW0PiTto5aTiUvT0UBh_ds8SZw72-0Dl2xAmCwz5jcbMnnzrJj0k77d8BwfT33StUl94n3ddrPJ4dLN-KUI6VwAg8LoQzG3PzwXjYgITp8ZBNsx6AqktDCunKFalFhHmH3qQzGYw"/>
              <div className="text-left">
                <div className="font-display-lg font-bold text-xl text-on-background">Ramesh K. Iyer</div>
                <div class="text-sm font-medium text-primary">Senior Advocate, Supreme Court of India</div>
              </div>
            </div>
          </div>
        </section>

        {/* Interactive FAQ Section */}
        <section className="bg-white py-24">
          <div className="max-w-3xl mx-auto px-4 md:px-10">
            <div className="text-center mb-16">
              <h2 className="font-display-lg text-4xl md:text-5xl font-bold text-on-background mb-4">Frequently Asked Questions</h2>
              <p className="text-lg text-on-surface-variant">Common inquiries from legal professionals.</p>
            </div>
            <div className="space-y-4">
              <details className="group border-2 border-outline-variant rounded-xl bg-white hover:border-primary/50 transition-colors" open>
                <summary className="flex justify-between items-center font-bold text-lg cursor-pointer p-6 text-on-background list-none">
                  Are the generated precedents actually citable in court?
                  <span className="material-symbols-outlined transition-transform duration-300 group-open:rotate-180 text-primary">expand_more</span>
                </summary>
                <div className="px-6 pb-6 text-on-surface-variant text-base leading-relaxed border-t-2 border-outline-variant/30 pt-4 mt-2">
                  Yes. Unlike general-purpose AI, Writon is strictly grounded in our proprietary database of authenticated Indian Supreme Court and High Court judgments. Every citation provided exists and includes correct AIR/SCC citations.
                </div>
              </details>
              
              <details className="group border-2 border-outline-variant rounded-xl bg-white hover:border-primary/50 transition-colors">
                <summary className="flex justify-between items-center font-bold text-lg cursor-pointer p-6 text-on-background list-none">
                  Is my client data secure and confidential?
                  <span className="material-symbols-outlined transition-transform duration-300 group-open:rotate-180 text-primary">expand_more</span>
                </summary>
                <div className="px-6 pb-6 text-on-surface-variant text-base leading-relaxed border-t-2 border-outline-variant/30 pt-4 mt-2">
                  Absolutely. We employ bank-level encryption (AES-256) for all data in transit and at rest. Your drafting data is completely segregated and is never used to train our base AI models. We comply fully with Indian data protection standards.
                </div>
              </details>

              <details className="group border-2 border-outline-variant rounded-xl bg-white hover:border-primary/50 transition-colors">
                <summary className="flex justify-between items-center font-bold text-lg cursor-pointer p-6 text-on-background list-none">
                  Does it support regional High Court formats?
                  <span className="material-symbols-outlined transition-transform duration-300 group-open:rotate-180 text-primary">expand_more</span>
                </summary>
                <div className="px-6 pb-6 text-on-surface-variant text-base leading-relaxed border-t-2 border-outline-variant/30 pt-4 mt-2">
                  Yes, Writon currently supports standard formatting and procedural templates for 28 High Courts across India, in addition to the Supreme Court and major tribunals like NCLT and NGT.
                </div>
              </details>
            </div>
          </div>
        </section>

        {/* Final CTA Banner */}
        <section className="bg-[#293044] text-white py-32 px-4 md:px-10 text-center relative overflow-hidden">
          <div className="absolute inset-0 opacity-10 bg-[url('data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyMCIgaGVpZ2h0PSIyMCI+CjxyZWN0IHdpZHRoPSIyMCIgaGVpZ2h0PSIyMCIgZmlsbD0ibm9uZSI+PC9yZWN0Pgo8Y2lyY2xlIGN4PSIyIiBjeT0iMiIgcj0iMiIgZmlsbD0iI2ZmZmZmZiI+PC9jaXJjbGU+Cjwvc3ZnPg==')]"></div>
          <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-primary/20 rounded-full blur-[120px] -mr-64 -mt-64"></div>
          <div className="max-w-3xl mx-auto relative z-10 space-y-10">
            <h2 className="font-display-lg text-5xl md:text-6xl font-bold text-white leading-tight">Ready to modernize your practice?</h2>
            <p className="font-body-lg text-xl text-[#dbe2fc] opacity-90 max-w-xl mx-auto">Join 5,000+ advocates drafting with scholarly precision.</p>
            <Link href="/dashboard" className="bg-primary text-white px-12 py-5 rounded-full font-bold text-lg hover:bg-[#0a523f] hover:-translate-y-1 hover:shadow-[0_0_40px_rgba(14,107,82,0.5)] transition-all shadow-xl active:scale-95 inline-flex items-center justify-center gap-3 mx-auto">
              Open the Drafting Wizard <span className="material-symbols-outlined text-2xl animate-pulse">magic_button</span>
            </Link>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="w-full px-4 md:px-10 py-16 bg-white border-t border-outline-variant mt-auto">
        <div className="max-w-[1280px] mx-auto flex flex-col md:flex-row justify-between items-start gap-12">
          <div className="flex flex-col gap-6 max-w-sm">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-primary text-3xl">gavel</span>
              <span className="font-display-lg text-2xl text-primary font-bold">Writon</span>
            </div>
            <p className="text-on-surface-variant text-sm leading-relaxed">Specialized AI for the Indian Legal Fraternity. Elevating precision, efficiency, and scholarly rigor in legal drafting.</p>
          </div>
          <div className="grid grid-cols-2 gap-16">
            <div className="flex flex-col gap-5">
              <span className="text-xs uppercase tracking-widest text-on-background font-bold">Platform</span>
              <Link className="text-sm font-medium text-on-surface-variant hover:text-primary transition-colors duration-300" href="/account">Pricing Plans</Link>
              <Link className="text-sm font-medium text-on-surface-variant hover:text-primary transition-colors duration-300" href="/search">Precedent Database</Link>
              <Link className="text-sm font-medium text-on-surface-variant hover:text-primary transition-colors duration-300" href="#">Product Overview</Link>
            </div>
            <div className="flex flex-col gap-5">
              <span className="text-xs uppercase tracking-widest text-on-background font-bold">Legal</span>
              <Link className="text-sm font-medium text-on-surface-variant hover:text-primary transition-colors duration-300" href="#">Terms of Service</Link>
              <Link className="text-sm font-medium text-on-surface-variant hover:text-primary transition-colors duration-300" href="#">Privacy Policy</Link>
              <Link className="text-sm font-medium text-on-surface-variant hover:text-primary transition-colors duration-300" href="#">Disclaimer</Link>
            </div>
          </div>
          <div className="w-full md:w-auto mt-8 md:mt-0 pt-8 md:pt-0 border-t md:border-0 border-outline-variant flex flex-col gap-3">
            <p className="text-xs font-semibold text-outline">© 2024 Writon. All rights reserved.</p>
            <div className="flex gap-4 mt-2">
              <span className="material-symbols-outlined text-outline hover:text-primary cursor-pointer transition-colors duration-300">language</span>
              <span className="material-symbols-outlined text-outline hover:text-primary cursor-pointer transition-colors duration-300">verified_user</span>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
