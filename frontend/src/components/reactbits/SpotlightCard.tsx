// React Bits TS-CSS, d37099f; adapted for the studio. See THIRD_PARTY.md.
import React, { useRef } from 'react';
import './SpotlightCard.css';
import { useReducedEffects } from './useReducedEffects';
import { useRevealOnce } from '../RevealSection';

interface Position {
  x: number;
  y: number;
}

interface SpotlightCardProps extends React.PropsWithChildren {
  className?: string;
  spotlightColor?: `rgba(${number}, ${number}, ${number}, ${number})`;
  reveal?: boolean;
}

const SpotlightCard: React.FC<SpotlightCardProps> = ({
  children,
  className = '',
  spotlightColor,
  reveal = false,
}) => {
  const visibility = useRevealOnce<HTMLDivElement>();
  const staticRef = useRef<HTMLDivElement>(null);
  const divRef = reveal ? visibility.ref : staticRef;
  const reduced = useReducedEffects();

  const handleMouseMove: React.MouseEventHandler<HTMLDivElement> = (e) => {
    if (!divRef.current || reduced) return;

    const rect = divRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    divRef.current.style.setProperty('--mouse-x', `${x}px`);
    divRef.current.style.setProperty('--mouse-y', `${y}px`);
    if (spotlightColor) divRef.current.style.setProperty('--spotlight-color', spotlightColor);
  };

  return (
    <div
      ref={divRef}
      data-motion-visible={reveal ? visibility['data-motion-visible'] : undefined}
      onMouseMove={reduced ? undefined : handleMouseMove}
      className={`card-spotlight ${className}`}
    >
      {children}
    </div>
  );
};

export default SpotlightCard;
