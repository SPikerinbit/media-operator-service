"use client";

import { ChevronDown } from "lucide-react";
import { type HTMLMotionProps, isValidMotionProp, motion, useReducedMotion } from "motion/react";
import {
  cloneElement,
  createContext,
  type ComponentProps,
  type ReactElement,
  type Ref,
  type RefObject,
  useCallback,
  useContext,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { cn, SPRING_LAYOUT } from "../helpers";

export type CollapsibleState = {
  open: boolean;
  disabled: boolean;
  setOpen: (open: boolean) => void;
  toggle: () => void;
};

type CollapsibleContextValue = CollapsibleState & {
  reduce: boolean;
  contentId: string;
  triggerId: string;
  triggerRef: RefObject<HTMLButtonElement | null>;
};

const CollapsibleContext = createContext<CollapsibleContextValue | null>(null);

function useCollapsibleContext(component: string) {
  const context = useContext(CollapsibleContext);
  if (!context) throw new Error(`${component} must be used within <Collapsible>`);
  return context;
}

/** Shared state and actions for custom children inside a Collapsible root. */
export function useCollapsible(): CollapsibleState {
  return useCollapsibleContext("useCollapsible");
}

function mergeRefs<T>(...refs: Array<Ref<T> | undefined>) {
  return (node: T | null) => {
    const cleanups = refs.map((ref) => {
      if (typeof ref === "function") return ref(node);
      if (ref) ref.current = node;
      return undefined;
    });
    if (!node) return;
    return () => {
      refs.forEach((ref, index) => {
        const cleanup = cleanups[index];
        if (typeof cleanup === "function") cleanup();
        else if (typeof ref === "function") ref(null);
        else if (ref) ref.current = null;
      });
    };
  };
}

export interface CollapsibleProps extends Omit<HTMLMotionProps<"div">, "layout"> {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  disabled?: boolean;
  /** Layout classes for the inner wrapper, separate from the animated surface. */
  contentClassName?: string;
}

export function Collapsible({
  open: controlledOpen,
  defaultOpen = false,
  onOpenChange,
  disabled = false,
  className,
  contentClassName,
  children,
  style,
  ...props
}: CollapsibleProps) {
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const open = controlledOpen ?? internalOpen;
  const reduce = useReducedMotion() ?? false;
  const id = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const stateRef = useRef({ open, controlled: controlledOpen !== undefined, disabled, onOpenChange });
  useLayoutEffect(() => {
    stateRef.current = { open, controlled: controlledOpen !== undefined, disabled, onOpenChange };
  }, [controlledOpen, disabled, onOpenChange, open]);
  const setOpen = useCallback((next: boolean) => {
    const state = stateRef.current;
    if (state.disabled || next === state.open) return;
    if (!state.controlled) {
      stateRef.current = { ...state, open: next };
      setInternalOpen(next);
    }
    state.onOpenChange?.(next);
  }, []);
  const toggle = useCallback(() => setOpen(!stateRef.current.open), [setOpen]);
  const context = useMemo<CollapsibleContextValue>(
    () => ({ open, disabled, reduce, contentId: `${id}-content`, triggerId: `${id}-trigger`, triggerRef, setOpen, toggle }),
    [disabled, id, open, reduce, setOpen, toggle],
  );

  return (
    <CollapsibleContext.Provider value={context}>
      <motion.div
        {...props}
        data-slot="collapsible"
        data-state={open ? "open" : "closed"}
        data-disabled={disabled || undefined}
        className={cn("relative w-full", className)}
        style={{ ...style, originY: 0 }}
      >
        <motion.div
          style={{ originY: 0 }}
          className={cn("min-w-0", contentClassName)}
        >
          {children}
        </motion.div>
      </motion.div>
    </CollapsibleContext.Provider>
  );
}

export interface CollapsibleTriggerProps extends Omit<HTMLMotionProps<"button">, "id" | "layout"> {
  /** Reuse a button element or a component that forwards its props and ref to a button. */
  render?: ReactElement;
}

export function CollapsibleTrigger({
  className,
  children,
  onClick,
  disabled,
  ref,
  render,
  style,
  ...props
}: CollapsibleTriggerProps) {
  const context = useCollapsibleContext("CollapsibleTrigger");
  const child = render as ReactElement<HTMLMotionProps<"button">> | undefined;
  const childRef = child?.props.ref;
  const mergedRef = useMemo(
    () => mergeRefs(context.triggerRef, ref, childRef),
    [context.triggerRef, ref, childRef],
  );
  const unavailable = context.disabled || disabled || child?.props.disabled;
  const handleClick: NonNullable<HTMLMotionProps<"button">["onClick"]> = (event) => {
    child?.props.onClick?.(event);
    onClick?.(event);
    if (!event.defaultPrevented && !unavailable) context.toggle();
  };
  const triggerProps = {
    id: context.triggerId,
    type: "button" as const,
    disabled: unavailable,
    "aria-expanded": context.open,
    "aria-controls": context.contentId,
    "data-slot": "collapsible-trigger",
    "data-state": context.open ? "open" : "closed",
    "data-disabled": unavailable || undefined,
    onClick: handleClick,
    ref: mergedRef,
  };

  if (child) {
    if (typeof child.type === "string" && child.type !== "button") {
      throw new Error("CollapsibleTrigger render must be a button or a component that renders a button.");
    }
    const forwarded = typeof child.type === "string"
      ? Object.fromEntries(Object.entries(props).filter(([key]) => !isValidMotionProp(key)))
      : props;
    return cloneElement(child, {
      ...forwarded,
      ...triggerProps,
      className: cn(className, child.props.className),
      style: { ...style, ...child.props.style },
      children: children === undefined ? child.props.children : children,
    });
  }

  return (
    <motion.button
      {...props}
      {...triggerProps}
      style={style}
      transition={{ layout: SPRING_LAYOUT }}
      className={cn(
        "flex min-h-10 w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm font-medium outline-none transition-colors hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50",
        className,
      )}
    >
      {children}
    </motion.button>
  );
}

export function CollapsibleContent({
  ref,
  ...props
}: ComponentProps<"div">) {
  const context = useCollapsibleContext("CollapsibleContent");
  const contentRef = useRef<HTMLDivElement>(null);
  const mergedRef = useMemo(() => mergeRefs(contentRef, ref), [ref]);

  useLayoutEffect(() => {
    if (!context.open && contentRef.current?.contains(document.activeElement)) {
      context.triggerRef.current?.focus({ preventScroll: true });
    }
  }, [context.open, context.triggerRef]);

  return (
    <div
      {...props}
      ref={mergedRef}
      id={context.contentId}
      role="region"
      aria-labelledby={context.triggerId}
      aria-hidden={context.open ? undefined : true}
      {...(context.open ? {} : { inert: true as const })}
      data-slot="collapsible-content"
      data-state={context.open ? "open" : "closed"}
    >
      <div>{props.children}</div>
    </div>
  );
}

export interface CollapsibleIndicatorProps extends HTMLMotionProps<"span"> {}

export function CollapsibleIndicator({ className, children, ...props }: CollapsibleIndicatorProps) {
  const { open, reduce } = useCollapsibleContext("CollapsibleIndicator");
  return (
    <motion.span
      {...props}
      aria-hidden="true"
      data-slot="collapsible-indicator"
      initial={false}
      animate={{ transform: `rotate(${open ? 180 : 0}deg)` }}
      transition={reduce ? { duration: 0 } : SPRING_LAYOUT}
      className={cn("ml-auto inline-flex shrink-0 items-center justify-center text-muted-foreground", className)}
    >
      {children ?? <ChevronDown className="size-4" />}
    </motion.span>
  );
}

