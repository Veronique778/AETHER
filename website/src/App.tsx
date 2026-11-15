import { BodySection } from './sections/BodySection';
import { Download, Footer } from './sections/Download';
import { Evidence } from './sections/Evidence';
import { Explore } from './sections/Explore';
import { Hero, Nav } from './sections/Hero';
import { PhantomDemo } from './sections/PhantomDemo';
import { Problem } from './sections/Problem';

export function App() {
  return (
    <div className="site-bg min-h-screen text-ink">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-lg focus:bg-teal-300 focus:px-3 focus:py-2 focus:text-canvas">Skip to content</a>
      <Nav />
      <main id="main">
        <Hero />
        <Problem />
        <BodySection />
        <PhantomDemo />
        <Evidence />
        <Explore />
        <Download />
      </main>
      <Footer />
    </div>
  );
}
