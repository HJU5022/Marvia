"use client";

// 채팅창. 문장 입력, 카톡 캡처 업로드, 되묻기(questions) 표시.

import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Preset, Stage } from "@/types/agent";
import Progress from "./Progress";

export interface ChatMessage {
  id: number;
  role: "user" | "agent" | "error";
  text: string;
  questions?: string[];
  image?: boolean;
}

export interface ChatSend {
  text: string | null;
  image_base64: string | null;
  preset: Preset | null;
}

interface Props {
  messages: ChatMessage[];
  busy: boolean;
  stage: Stage | null;
  onSend: (input: ChatSend) => void;
  children?: ReactNode; // 입력창 위에 붙는 단계별 버튼
}

const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

function readBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export default function ChatPanel({ messages, busy, stage, onSend, children }: Props) {
  const [text, setText] = useState("");
  const [preset, setPreset] = useState<Preset | "">("");
  const [image, setImage] = useState<File | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  const pickImage = (file: File | null) => {
    setLocalError(null);
    if (!file) return setImage(null);
    if (!["image/png", "image/jpeg"].includes(file.type)) {
      setLocalError("PNG 또는 JPG 캡처만 올릴 수 있습니다");
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setLocalError("캡처가 5MB 를 넘습니다");
      return;
    }
    setImage(file);
  };

  const submit = async () => {
    const trimmed = text.trim();
    if (busy || (!trimmed && !image)) return;
    let image_base64: string | null = null;
    if (image) {
      try {
        image_base64 = await readBase64(image);
      } catch {
        setLocalError("캡처를 읽지 못했습니다");
        return;
      }
    }
    onSend({ text: trimmed || null, image_base64, preset: preset || null });
    setText("");
    setImage(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <section className="chat">
      <div className="chat-list" ref={listRef} aria-live="polite">
        {messages.length === 0 && (
          <div className="chat-guide">
            <p>
              <strong>이렇게 입력해 보세요</strong>
            </p>
            <ul>
              <li>누가, 어디서 출발하고, 무엇을 타고 오는지</li>
              <li>현장(예: 진해 기지, 여의도 고객사)과 시각</li>
              <li>출입조치 신청 여부, 태워 줄 사람이 있으면 그 지점</li>
            </ul>
            <p className="muted">카톡 대화 캡처를 올려도 됩니다.</p>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`msg msg-${m.role}`}>
            {m.image && <span className="badge">캡처 첨부</span>}
            <p>{m.text}</p>
            {m.questions && m.questions.length > 0 && (
              <ol className="questions">
                {m.questions.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ol>
            )}
          </div>
        ))}
        {busy && <div className="msg msg-agent pending">계산 중입니다…</div>}
      </div>

      <Progress busy={busy} stage={stage} />

      {children && <div className="chat-actions">{children}</div>}

      <form
        className="chat-form"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="chat-form-row">
          <select value={preset} onChange={(e) => setPreset(e.target.value as Preset | "")} aria-label="작업 종류">
            <option value="">작업 종류 자동</option>
            <option value="ship_maintenance">함정 정비</option>
            <option value="si_deploy">SI 배포·미팅</option>
          </select>
          <label className="file-btn">
            캡처 올리기
            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/jpeg"
              onChange={(e) => pickImage(e.target.files?.[0] ?? null)}
            />
          </label>
          {image && (
            <button type="button" className="link" onClick={() => pickImage(null)}>
              {image.name} 빼기
            </button>
          )}
        </div>
        {localError && <p className="error">{localError}</p>}
        <div className="chat-form-row">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void submit();
              }
            }}
            placeholder="예: 목요일 08:00 진해 기지 레이더 점검. 업체 두 분은 부산에서 차로 오세요"
            rows={3}
          />
          <button type="submit" disabled={busy || (!text.trim() && !image)}>
            보내기
          </button>
        </div>
      </form>
    </section>
  );
}
