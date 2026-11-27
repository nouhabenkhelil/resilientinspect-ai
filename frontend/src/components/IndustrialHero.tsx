import industrialHero from '../assets/industrial-ai-hero.svg?raw';

export function IndustrialHero() {
  return (
    <figure className="architecture-graphic industrial-hero">
      {/* Trusted, bundled SVG only. Decorative: never fed prediction data. */}
      <div className="industrial-hero-art" aria-hidden="true"
        dangerouslySetInnerHTML={{ __html: industrialHero }} />
      <figcaption>
        <span>VISION INDUSTRIELLE</span>
        <small>Illustration conceptuelle · aucune analyse en cours</small>
      </figcaption>
    </figure>
  );
}
