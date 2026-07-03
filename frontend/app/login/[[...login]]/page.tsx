import { SignIn } from "@clerk/nextjs";
import Navbar from "@/components/shared/Navbar";

export default function LoginPage() {
  return (
    <div className="min-h-screen bg-surface flex flex-col font-body-md">
      <Navbar />
      <main className="flex-1 flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8 paper-texture">
        <div className="animate-fade-slide-up">
          <SignIn 
            path="/login"
            appearance={{
              elements: {
                rootBox: "mx-auto",
                card: "bg-white shadow-lg border border-outline-variant rounded-xl p-8",
                headerTitle: "font-display-lg text-3xl text-on-background",
                headerSubtitle: "text-on-surface-variant font-body-md",
                formButtonPrimary: "bg-primary hover:bg-[#004131] text-white font-bold py-3 rounded-lg shadow-sm transition-all duration-300",
                formFieldLabel: "text-sm font-semibold text-on-surface mb-2",
                formFieldInput: "px-4 py-3 border border-outline-variant rounded-lg focus:ring-2 focus:ring-primary focus:border-primary outline-none transition-all",
                footerActionLink: "text-primary hover:text-[#004131] font-semibold",
                identityPreviewText: "text-on-surface",
                identityPreviewEditButtonIcon: "text-primary",
              }
            }}
          />
        </div>
      </main>
    </div>
  );
}
