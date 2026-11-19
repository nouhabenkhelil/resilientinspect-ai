// React Bits TS-CSS, d37099f; adapted for the studio. See THIRD_PARTY.md.
import './ShinyText.css';
import { useReducedEffects } from './useReducedEffects';

interface ShinyTextProps {
  text: string;
  disabled?: boolean;
  speed?: number;
  className?: string;
}

const ShinyText: React.FC<ShinyTextProps> = ({
  text,
  disabled = false,
  speed = 5,
  className = '',
}) => {
  const reduced = useReducedEffects();
  const animationDuration = `${speed}s`;

  return (
    <span
      className={`shiny-text ${disabled || reduced ? 'disabled' : ''} ${className}`}
      style={{ animationDuration }}
    >
      {text}
    </span>
  );
};

export default ShinyText;
