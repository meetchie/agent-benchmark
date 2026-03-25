import { FlickeringGrid } from "./FlickeringGrid";
import { HeroFluidGradient } from "./HeroFluidGradient";

interface HeroSectionProps {
  onSignInClick?: () => void;
  onCTA?: () => void;
}

export function HeroSection({ onSignInClick, onCTA }: HeroSectionProps) {

  return (
    <section className="min-h-[90vh] w-full bg-[#f0f4ff]">
      {/* Nav bar — same dims as main site TopNav */}
      <nav className="relative z-50 mx-4 flex items-center justify-between pt-2 pb-3 sm:mx-8 md:mx-14 md:pt-3 md:pb-4 lg:mx-24">
        <div className="flex items-center gap-2 sm:gap-3 text-2xl font-semibold tracking-tight text-black">
          <img src="/rindler-logo.png" alt="Rindler" className="h-9 w-auto object-contain sm:h-12" />
          <span className="hidden sm:inline">Rindler</span>
        </div>
        <button
          onClick={onSignInClick}
          className="inline-flex items-center border-2 border-black bg-transparent px-3 py-1.5 text-sm font-medium text-black transition-all duration-200 hover:bg-black/10 sm:px-4 sm:py-2"
        >
          Sign In
        </button>
      </nav>

      {/* Hero block — same dims as main site Hero */}
      <div
        className="relative mx-4 min-h-[82vh] overflow-hidden sm:mx-8 md:mx-14 lg:mx-24"
        style={{ background: "linear-gradient(135deg, #3c49ad 0%, #4a58b8 40%, #5a67c0 100%)" }}
      >
        {/* Animation layers */}
        <HeroFluidGradient />
        <FlickeringGrid />

        {/* Content — centered vertically */}
        <div className="relative z-20 flex min-h-[82vh] flex-col justify-center px-6 md:px-12 lg:px-16">
          <div className="max-w-xl">
            <h1 className="text-4xl sm:text-5xl md:text-6xl font-extrabold tracking-tight text-white leading-[1.08]">
              The AI economy
              <br />
              is here.
            </h1>
            <p className="mt-4 text-sm md:text-base text-white/70 leading-relaxed max-w-sm">
              AI agents are becoming the new customers.
              <br />
              See how your site performs when they show up.
            </p>
            <button
              onClick={onCTA}
              className="group mt-7 inline-flex items-center gap-2 bg-white text-[#3c49ad] font-bold text-sm px-6 py-3 hover:bg-white/90 transition-all"
            >
              Test Your Site
              <span className="inline-block transition-transform group-hover:translate-x-1">→</span>
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
