import { useEffect, useRef, useState } from 'react';

/**
 * Production-grade debounce hook.
 *
 * Features:
 * - Cancels the pending timer on every new value (standard debounce).
 * - Enforces a `minLength` guard: values shorter than the minimum are treated
 *   as empty string so callers don't fire expensive queries on 1–2 chars.
 * - Returns `isPending` so callers can show a subtle "typing…" indicator
 *   without waiting for the full delay.
 *
 * @param value     - the raw, live value to debounce (e.g. search input)
 * @param delay     - debounce delay in ms (default: 400)
 * @param minLength - minimum value length before the debounced value updates
 *                    (default: 2). Set to 0 to disable.
 */
export function useDebounce<T extends string>(
  value: T,
  delay = 400,
  minLength = 2,
): { debouncedValue: string; isPending: boolean } {
  // The value we actually expose to the consumer after debouncing
  const [debouncedValue, setDebouncedValue] = useState<string>(
    value.length >= minLength ? value : '',
  );

  // Track whether a debounce timer is running (user is still typing)
  const [isPending, setIsPending] = useState(false);

  // Keep a stable ref to the latest value so the timeout closure is fresh
  const valueRef = useRef(value);
  valueRef.current = value;

  useEffect(() => {
    // If the input is cleared or below the minimum, flush immediately —
    // no need to wait for the timer.
    if (value.length < minLength) {
      setDebouncedValue('');
      setIsPending(false);
      return;
    }

    setIsPending(true);

    const timer = setTimeout(() => {
      setDebouncedValue(valueRef.current.length >= minLength ? valueRef.current : '');
      setIsPending(false);
    }, delay);

    return () => {
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, delay, minLength]);

  return { debouncedValue, isPending };
}
