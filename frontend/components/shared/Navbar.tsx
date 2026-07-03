import { SignedIn, SignedOut, UserButton } from "@clerk/nextjs";
import Link from "next/link";

export default function Navbar() {
  return (
    <header className="sticky top-0 z-50 flex justify-between items-center w-full px-margin-desktop py-4 bg-surface-container-lowest border-b border-outline-variant">
      <div className="flex items-center gap-8">
        {/* Replace with actual logo later */}
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-primary text-3xl">gavel</span>
          <span className="font-display-lg text-xl text-primary font-bold">Writon</span>
        </div>
        <nav className="hidden md:flex gap-6">
          <SignedOut>
            <Link
              href="/"
              className="font-label-md text-label-md text-primary border-b-2 border-primary pb-1 transition-colors duration-300"
            >
              Home
            </Link>
          </SignedOut>
          <SignedIn>
            <Link
              href="/dashboard"
              className="font-label-md text-label-md text-on-surface-variant hover:text-primary transition-colors duration-300"
            >
              Dashboard
            </Link>
          </SignedIn>
          <Link
            href="/search"
            className="font-label-md text-label-md text-on-surface-variant hover:text-primary transition-colors duration-300"
          >
            SC Precedents
          </Link>
          <Link
            href="/account"
            className="font-label-md text-label-md text-on-surface-variant hover:text-primary transition-colors duration-300"
          >
            Pricing
          </Link>
        </nav>
      </div>
      <div className="flex items-center gap-4">
        <SignedOut>
          <Link
            href="/login"
            className="font-label-md text-label-md text-on-surface-variant hover:text-primary transition-colors duration-300 px-2"
          >
            Login
          </Link>
          <Link
            href="/signup"
            className="hover:-translate-y-0.5 hover:shadow-[0_4px_14px_rgba(14,107,82,0.3)] active:scale-95 transition-all duration-300 px-6 py-2.5 rounded-lg bg-primary text-white font-label-md text-label-md font-bold"
          >
            Sign Up
          </Link>
        </SignedOut>
        <SignedIn>
          <UserButton 
            afterSignOutUrl="/" 
            userProfileProps={{
              apiKeysProps: { hide: true }
            }}
          />
        </SignedIn>
      </div>
    </header>
  );
}
