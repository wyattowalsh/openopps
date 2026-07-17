"use client";

import { type RefObject, useEffect, useRef } from "react";

const FOCUSABLE_SELECTOR = [
	"a[href]",
	"button:not([disabled])",
	"textarea:not([disabled])",
	"input:not([disabled])",
	"select:not([disabled])",
	'[tabindex]:not([tabindex="-1"])',
].join(",");

export type DialogFocusMove = "dialog" | "first" | "last" | "none";

export function shouldCloseDialogFromKey(key: string) {
	return key === "Escape";
}

export function resolveDialogTabMove({
	activeIndex,
	focusableCount,
	shiftKey,
}: {
	activeIndex: number;
	focusableCount: number;
	shiftKey: boolean;
}): DialogFocusMove {
	if (focusableCount <= 0) {
		return "dialog";
	}
	if (activeIndex < 0) {
		return shiftKey ? "last" : "first";
	}
	if (shiftKey && activeIndex === 0) {
		return "last";
	}
	if (!shiftKey && activeIndex === focusableCount - 1) {
		return "first";
	}
	return "none";
}

export function getDialogFocusableElements(root: HTMLElement) {
	return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
		(element) =>
			element.tabIndex >= 0 &&
			!element.hidden &&
			element.getAttribute("aria-hidden") !== "true",
	);
}

export function useDialogFocusTrap(
	open: boolean,
	dialogRef: RefObject<HTMLElement | null>,
	onClose: () => void,
) {
	const onCloseRef = useRef(onClose);

	useEffect(() => {
		onCloseRef.current = onClose;
	}, [onClose]);

	useEffect(() => {
		if (!open || !dialogRef.current) {
			return;
		}
		const dialog = dialogRef.current;
		const previouslyFocused =
			document.activeElement instanceof HTMLElement
				? document.activeElement
				: null;
		const previous = document.body.style.overflow;
		document.body.style.overflow = "hidden";
		const focusFrame = window.requestAnimationFrame(() => {
			const target = getDialogFocusableElements(dialog)[0] ?? dialog;
			target.focus({ preventScroll: true });
		});

		function handleKeyDown(event: KeyboardEvent) {
			if (shouldCloseDialogFromKey(event.key)) {
				event.preventDefault();
				onCloseRef.current();
				return;
			}
			if (event.key !== "Tab") {
				return;
			}
			const focusable = getDialogFocusableElements(dialog);
			const activeIndex = focusable.indexOf(document.activeElement as HTMLElement);
			const move = resolveDialogTabMove({
				activeIndex,
				focusableCount: focusable.length,
				shiftKey: event.shiftKey,
			});
			if (move === "none") {
				return;
			}
			event.preventDefault();
			if (move === "dialog") {
				dialog.focus({ preventScroll: true });
				return;
			}
			const target = move === "first" ? focusable[0] : focusable.at(-1);
			target?.focus({ preventScroll: true });
		}

		document.addEventListener("keydown", handleKeyDown);
		return () => {
			window.cancelAnimationFrame(focusFrame);
			document.removeEventListener("keydown", handleKeyDown);
			document.body.style.overflow = previous;
			previouslyFocused?.focus({ preventScroll: true });
		};
	}, [dialogRef, open]);
}
