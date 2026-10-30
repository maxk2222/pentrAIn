declare module "@novnc/novnc" {
  export interface RFBCredentials {
    password?: string;
    username?: string;
    target?: string;
  }
  export interface RFBOptions {
    credentials?: RFBCredentials;
    shared?: boolean;
    repeaterID?: string;
    wsProtocols?: string[];
  }
  export default class RFB {
    constructor(target: HTMLElement, urlOrChannel: string | WebSocket, options?: RFBOptions);
    viewOnly: boolean;
    scaleViewport: boolean;
    resizeSession: boolean;
    background: string;
    focusOnClick: boolean;
    clipViewport: boolean;
    dragViewport: boolean;
    showDotCursor: boolean;
    qualityLevel: number;
    compressionLevel: number;
    disconnect(): void;
    sendCredentials(credentials: RFBCredentials): void;
    sendCtrlAltDel(): void;
    sendKey(keysym: number, code: string | null, down?: boolean): void;
    clipboardPasteFrom(text: string): void;
    addEventListener(type: string, listener: (e: CustomEvent) => void): void;
    removeEventListener(type: string, listener: (e: CustomEvent) => void): void;
  }
}
