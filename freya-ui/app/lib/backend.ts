/**
 * Where Freya's backend (server.py) listens.
 *
 * start-freya picks free ports each time it starts - 8000 when it's free, the
 * next free one when another app holds it - and passes the address in
 * NEXT_PUBLIC_FREYA_API. Started any other way, the default applies.
 */
export const BACKEND = (process.env.NEXT_PUBLIC_FREYA_API || "http://localhost:8000").replace(/\/+$/, "");

/** The live event socket. */
export const BACKEND_WS = `${BACKEND.replace(/^http/, "ws")}/ws`;
