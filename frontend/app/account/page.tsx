import Navbar from '@/components/shared/Navbar';

export default function PricingPage() {
  return (
    <div className="font-body-md text-on-surface bg-[#FAF9F6] min-h-screen relative selection:bg-primary-fixed selection:text-on-primary-fixed">
      {/* Paper texture background overlay */}
      <div 
        className="fixed inset-0 z-0 pointer-events-none opacity-[0.03]"
        style={{ backgroundImage: 'url("https://www.transparenttextures.com/patterns/parchment.png")' }}
      ></div>
      
      <div className="relative z-10 flex flex-col min-h-screen">
        <Navbar />

        {/* Pricing Hero */}
        <header className="max-w-[1280px] mx-auto px-4 md:px-10 pt-20 pb-16 text-center w-full">
          <h1 className="font-display-lg text-4xl md:text-5xl font-bold mb-4 text-on-background">Simple, Transparent Pricing</h1>
          <p className="font-body-lg text-lg text-on-surface-variant max-w-2xl mx-auto">
            Start free. Upgrade when you need more. Cancel anytime.
          </p>
        </header>

        {/* Pricing Grid */}
        <main className="max-w-[1280px] mx-auto px-4 md:px-10 pb-24 w-full">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 items-center">
            
            {/* Plan: Free */}
            <div className="bg-white p-8 rounded-xl border border-outline-variant flex flex-col h-[400px] hover:border-outline transition-all duration-300 group animate-fade-slide-up" style={{ animationDelay: '100ms', boxShadow: '0 4px 12px rgba(20, 27, 46, 0.04)' }}>
              <div className="mb-8">
                <h3 className="text-xs font-semibold uppercase text-on-surface-variant mb-2">Free</h3>
                <div className="flex items-baseline gap-1">
                  <span className="font-display-lg text-4xl font-bold">₹0</span>
                  <span className="text-sm font-semibold text-on-surface-variant">/mo</span>
                </div>
              </div>
              <ul className="space-y-4 mb-10 flex-grow">
                <li className="flex items-start gap-3">
                  <span className="material-symbols-outlined text-primary text-[20px]" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                  <span className="text-on-surface-variant text-sm">3 Documents / mo</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="material-symbols-outlined text-primary text-[20px]" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                  <span className="text-on-surface-variant text-sm">Standard Templates</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="material-symbols-outlined text-outline-variant text-[20px]">check_circle</span>
                  <span className="text-outline text-sm">No PDF Exports</span>
                </li>
              </ul>
              <button className="w-full py-3 border-2 border-primary text-primary text-sm font-semibold rounded-lg hover:bg-primary-fixed hover:scale-[1.02] transition-all duration-300 active:scale-95 mt-auto">
                Current Plan
              </button>
            </div>

            {/* Plan: Advocate (Highlighted) */}
            <div className="bg-white p-8 rounded-xl border-2 border-primary flex flex-col h-[440px] relative lg:scale-105 z-10 transition-all duration-300 animate-fade-slide-up" style={{ animationDelay: '200ms', boxShadow: '0 12px 24px rgba(14, 107, 82, 0.08)' }}>
              <div className="absolute -top-4 left-1/2 -translate-x-1/2 bg-[#B8860B] text-white px-4 py-1 rounded-full text-xs font-bold uppercase tracking-wider shadow-sm overflow-hidden group">
                <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/40 to-transparent -translate-x-full animate-[shimmer_3s_infinite]"></div>
                <span className="relative">Most Popular</span>
              </div>
              <div className="mb-8">
                <h3 className="text-xs font-semibold uppercase text-primary mb-2">Advocate</h3>
                <div className="flex items-baseline gap-1">
                  <span className="font-display-lg text-4xl font-bold text-primary">₹499</span>
                  <span className="text-sm font-semibold text-on-surface-variant">/mo</span>
                </div>
              </div>
              <ul className="space-y-4 mb-10 flex-grow">
                <li className="flex items-start gap-3">
                  <span className="material-symbols-outlined text-primary text-[20px]" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                  <span className="text-on-surface text-sm font-medium">Unlimited Drafts</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="material-symbols-outlined text-primary text-[20px]" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                  <span className="text-on-surface text-sm font-medium">Advanced SC Precedents</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="material-symbols-outlined text-primary text-[20px]" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                  <span className="text-on-surface text-sm font-medium">Priority Support</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="material-symbols-outlined text-primary text-[20px]" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                  <span className="text-on-surface text-sm font-medium">Custom Citations</span>
                </li>
              </ul>
              <button className="w-full py-3 bg-primary text-white text-sm font-semibold rounded-lg shadow-sm hover:bg-[#0a523f] hover:scale-[1.02] transition-all duration-300 active:scale-95 mt-auto">
                Get Started
              </button>
            </div>

            {/* Plan: Premium */}
            <div className="bg-white p-8 rounded-xl border border-outline-variant flex flex-col h-[400px] hover:border-outline transition-all duration-300 group animate-fade-slide-up" style={{ animationDelay: '300ms', boxShadow: '0 4px 12px rgba(20, 27, 46, 0.04)' }}>
              <div className="mb-8">
                <h3 className="text-xs font-semibold uppercase text-on-surface-variant mb-2">Premium</h3>
                <div className="flex items-baseline gap-1">
                  <span className="font-display-lg text-4xl font-bold">₹999</span>
                  <span className="text-sm font-semibold text-on-surface-variant">/mo</span>
                </div>
              </div>
              <ul className="space-y-4 mb-10 flex-grow">
                <li className="flex items-start gap-3">
                  <span className="material-symbols-outlined text-primary text-[20px]" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                  <span className="text-on-surface-variant text-sm">AI Clause Generator</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="material-symbols-outlined text-primary text-[20px]" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                  <span className="text-on-surface-variant text-sm">Team Collaboration (3 seats)</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="material-symbols-outlined text-primary text-[20px]" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                  <span className="text-on-surface-variant text-sm">White-labeled Exports</span>
                </li>
              </ul>
              <button className="w-full py-3 bg-primary text-white text-sm font-semibold rounded-lg shadow-sm hover:bg-[#0a523f] hover:scale-[1.02] transition-all duration-300 active:scale-95 mt-auto">
                Upgrade Now
              </button>
            </div>

            {/* Plan: Firm */}
            <div className="bg-white p-8 rounded-xl border border-outline-variant flex flex-col h-[400px] hover:border-outline transition-all duration-300 group animate-fade-slide-up" style={{ animationDelay: '400ms', boxShadow: '0 4px 12px rgba(20, 27, 46, 0.04)' }}>
              <div className="mb-8">
                <h3 className="text-xs font-semibold uppercase text-on-surface-variant mb-2">Firm</h3>
                <div className="flex items-baseline gap-1">
                  <span className="font-display-lg text-4xl font-bold">₹2,499</span>
                  <span className="text-sm font-semibold text-on-surface-variant">/mo</span>
                </div>
              </div>
              <ul className="space-y-4 mb-10 flex-grow">
                <li className="flex items-start gap-3">
                  <span className="material-symbols-outlined text-primary text-[20px]" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                  <span className="text-on-surface-variant text-sm">Unlimited Seats</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="material-symbols-outlined text-primary text-[20px]" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                  <span className="text-on-surface-variant text-sm">Custom API Access</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="material-symbols-outlined text-primary text-[20px]" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                  <span className="text-on-surface-variant text-sm">On-premise Deployment</span>
                </li>
              </ul>
              <button className="w-full py-3 border-2 border-primary text-primary text-sm font-semibold rounded-lg hover:bg-primary-fixed hover:scale-[1.02] transition-all duration-300 active:scale-95 mt-auto">
                Contact Sales
              </button>
            </div>

          </div>

          <div className="mt-16 text-center">
            <p className="text-sm text-outline">
              All prices exclusive of GST. Indian billing only. Cancel anytime from your dashboard.
            </p>
          </div>
        </main>

        {/* Visual Divider */}
        <section className="max-w-[1280px] mx-auto px-4 md:px-10 mb-24 w-full">
          <div className="relative h-64 rounded-2xl overflow-hidden" style={{ boxShadow: '0 4px 12px rgba(20, 27, 46, 0.04)' }}>
            <div 
              className="bg-cover bg-center w-full h-full" 
              style={{ backgroundImage: "url('https://lh3.googleusercontent.com/aida-public/AB6AXuAuQiq4hDjq8pracCvnq4eXAbkb0NSZ2Ezy07FprKHG9SMlPt3IJqAvUPXw-8IiLIApFI7kKWEU-eJe3jfkQSkUTZNnKfvFDSfBY7suOM8QPv-zBOWApSNMyO8G7bofRXJRtz3MKl1G3lmGCi8DCk3RYWU8S9bxEKF_JXWiWvCLSEj1ozUR85oIPhPsvmUqESTSn3UyvHnooea3qyCJ7tZksIlL7I2zGNwm3RZOCTAOO0Q0PTumNsJ8QQ')" }}
            ></div>
            <div className="absolute inset-0 bg-gradient-to-r from-primary/90 to-transparent flex items-center p-12">
              <div className="max-w-md text-white">
                <h2 className="font-display-lg text-3xl font-bold mb-4">Empowering 5,000+ Advocates</h2>
                <p className="text-white/90">Join the digital revolution in legal drafting and research. Precision meets efficiency.</p>
              </div>
            </div>
          </div>
        </section>

      </div>
    </div>
  );
}
