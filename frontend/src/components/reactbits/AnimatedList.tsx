// Adapted from React Bits TS-CSS AnimatedList. See frontend/THIRD_PARTY.md.
import { useRef, useState, type KeyboardEvent } from 'react';
import { motion, useInView } from 'motion/react';
import { useReducedEffects } from './useReducedEffects';
import './AnimatedList.css';

interface AnimatedListProps {
  items?: string[];
  onItemSelect?: (item: string, index: number) => void;
  className?: string;
  itemClassName?: string;
  enableArrowNavigation?: boolean;
  initialSelectedIndex?: number;
}

function AnimatedItem({
  item,
  index,
  onSelect,
  selected,
  className,
}: {
  item: string;
  index: number;
  onSelect?: () => void;
  selected: boolean;
  className: string;
}) {
  const ref = useRef<HTMLLIElement>(null);
  const emptyRef = useRef<HTMLLIElement>(null);
  const reduced = useReducedEffects();
  const canObserve = typeof IntersectionObserver !== 'undefined';
  const inView = useInView(canObserve ? ref : emptyRef, { once: true, amount: 0.1 });
  return (
    <motion.li
      ref={ref}
      data-index={index}
      initial={reduced ? false : { y: 8, opacity: 0 }}
      animate={reduced || !canObserve || inView ? { y: 0, opacity: 1 } : { y: 8, opacity: 0 }}
      transition={{ duration: reduced ? 0 : 0.2, delay: Math.min(index, 4) * 0.025 }}
    >
      {onSelect ? (
        <button
          type="button"
          className={`rb-list-item ${selected ? 'selected' : ''} ${className}`}
          onClick={onSelect}
        >
          {item}
        </button>
      ) : (
        <div className={`rb-list-item ${className}`}>{item}</div>
      )}
    </motion.li>
  );
}

export default function AnimatedList({
  items = [],
  onItemSelect,
  className = '',
  itemClassName = '',
  enableArrowNavigation = true,
  initialSelectedIndex = -1,
}: AnimatedListProps) {
  const [selected, setSelected] = useState(initialSelectedIndex);
  const navigate = (event: KeyboardEvent<HTMLUListElement>) => {
    if (!onItemSelect || !enableArrowNavigation || !['ArrowDown', 'ArrowUp'].includes(event.key))
      return;
    const buttons = Array.from(event.currentTarget.querySelectorAll('button'));
    const active = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next = Math.max(
      0,
      Math.min(buttons.length - 1, active + (event.key === 'ArrowDown' ? 1 : -1)),
    );
    event.preventDefault();
    buttons[next]?.focus();
  };
  return (
    <ul className={`rb-animated-list ${className}`} onKeyDown={navigate}>
      {items.map((item, index) => (
        <AnimatedItem
          key={`${index}-${item}`}
          item={item}
          index={index}
          selected={selected === index}
          className={itemClassName}
          onSelect={
            onItemSelect
              ? () => {
                  setSelected(index);
                  onItemSelect(item, index);
                }
              : undefined
          }
        />
      ))}
    </ul>
  );
}
