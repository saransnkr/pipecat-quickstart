import { useEffect, useState } from "react";
import type { PipecatBaseChildProps } from "@pipecat-ai/voice-ui-kit";
import { UserAudioControl } from "@pipecat-ai/voice-ui-kit";
import { Mic, PhoneOff, Sparkles } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { PlasmaVisualizer } from "@pipecat-ai/voice-ui-kit/webgl";
import { TranscriptOverlay } from "@pipecat-ai/voice-ui-kit";

type TranscriptMessage = {
  type: "transcript";
  speaker: string;
  text?: string;
};

const isTranscriptMessage = (value: unknown): value is TranscriptMessage => {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const candidate = value as Partial<TranscriptMessage>;
  return candidate.type === "transcript" && typeof candidate.speaker === "string";
};

export const App = ({
  client,
  handleConnect,
  handleDisconnect,
}: PipecatBaseChildProps) => {
  const [isOpen, setIsOpen] = useState(false);
  const [audioTrack, setAudioTrack] = useState<MediaStreamTrack | null>(null);
  const [isThinking, setIsThinking] = useState(false);
  const [transcript, setTranscript] = useState<{ speaker: string; text: string }>({
    speaker: "",
    text: "",
  });

  const conversationState = isThinking
    ? {
        label: "Responding",
        dotClass: "bg-emerald-400",
        accent: "from-emerald-400/30 via-emerald-500/10 to-transparent",
      }
    : transcript.text
    ? {
        label: "Listening",
        dotClass: "bg-sky-400",
        accent: "from-sky-400/30 via-sky-500/10 to-transparent",
      }
    : {
        label: "Ready",
        dotClass: "bg-slate-300",
        accent: "from-indigo-300/20 via-transparent to-transparent",
      };

  // Initialize Pipecat and mic
  useEffect(() => {
    client?.initDevices();
    if (!client) return;

    const onMessage = (message: unknown) => {
      if (!isTranscriptMessage(message)) {
        return;
      }

      setTranscript({
        speaker: message.speaker,
        text: message.text || "",
      });
      setIsThinking(message.speaker !== "user");
    };

    client.on("message", onMessage);
    return () => client.off("message", onMessage);
  }, [client]);

  // Handle connect/disconnect
  const handleToggle = async () => {
    if (!isOpen) {
      setIsOpen(true);
      await handleConnect?.();
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        setAudioTrack(stream.getAudioTracks()[0]);
      } catch (err) {
        console.error("Microphone access error:", err);
      }
    } else {
      await handleDisconnect?.();
      setIsOpen(false);
      if (audioTrack) {
        audioTrack.stop();
        setAudioTrack(null);
      }
      setTranscript({ speaker: "", text: "" });
      setIsThinking(false);
    }
  };

  return (
    <>
      <motion.button
        onClick={handleToggle}
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        whileTap={{ scale: 0.96 }}
        whileHover={{ scale: 1.04 }}
        className={`fixed bottom-6 right-6 z-50 flex h-16 w-16 items-center justify-center rounded-2xl border border-white/10 shadow-[0_20px_60px_-15px_rgba(15,23,42,0.6)] transition-all duration-300 
          ${isOpen
            ? "bg-gradient-to-br from-rose-500 to-amber-500 text-white"
            : "bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 text-slate-50"}
        `}
      >
        <motion.span
          animate={{ scale: isOpen ? [1, 1.08, 1] : 1 }}
          transition={{ duration: 1.8, repeat: isOpen ? Infinity : 0 }}
          className="relative inline-flex h-6 w-6 items-center justify-center"
        >
          {isOpen ? <PhoneOff size={22} /> : <Mic size={22} />}
          {isOpen && (
            <motion.span
              className="absolute inset-0 rounded-full bg-rose-400/30 blur-lg"
              animate={{ opacity: [0.5, 0.85, 0.5] }}
              transition={{ duration: 2, repeat: Infinity }}
            />
          )}
        </motion.span>
      </motion.button>

      <AnimatePresence>
        {isOpen && (
          <>
            <motion.div
              key="overlay"
              className="fixed inset-0 z-40 bg-slate-950/70 backdrop-blur-lg"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={handleToggle}
            />

            <motion.div
              key="panel"
              initial={{ opacity: 0, y: 40, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 20, scale: 0.98 }}
              transition={{ type: "spring", damping: 24, stiffness: 240 }}
              className="fixed bottom-6 right-6 z-50 w-520 max-w-[520px] h-[620px]"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="relative flex h-full flex-col overflow-hidden rounded-3xl border border-white/10 bg-slate-950/80 shadow-[0_40px_140px_-60px_rgba(15,23,42,0.9)] backdrop-blur-2xl">
                <div className="pointer-events-none absolute -left-24 -top-24 h-60 w-60 rounded-full bg-gradient-to-br from-sky-500/40 to-indigo-500/10 blur-3xl" />
                <div className="pointer-events-none absolute -right-20 bottom-10 h-56 w-56 rounded-full bg-gradient-to-br from-rose-500/30 via-purple-500/10 to-transparent blur-3xl" />

                <div className="relative flex h-full flex-col gap-6 p-6">
                  <header className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-sky-500 shadow-lg shadow-sky-900/40">
                        <Sparkles size={20} className="text-white" />
                      </div>
                      <div>
                        <p className="text-sm font-medium uppercase tracking-[0.18em] text-slate-400">Voice Agent</p>
                        <h2 className="text-xl font-semibold text-white">Real-time AI conversation</h2>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5">
                      <motion.span
                        animate={{ scale: [1, 1.3, 1] }}
                        transition={{ duration: 1.8, repeat: Infinity }}
                        className={`h-2.5 w-2.5 rounded-full ${conversationState.dotClass}`}
                      />
                      <span className="text-xs font-medium uppercase tracking-[0.2em] text-slate-200">
                        {conversationState.label}
                      </span>
                    </div>
                  </header>

                  <div className="relative flex flex-1 flex-col overflow-hidden rounded-2xl border border-white/10 bg-white/[0.02] p-6 shadow-inner">
                    <div className={`absolute inset-0 rounded-2xl bg-gradient-to-br ${conversationState.accent}`} />
                    <div className="relative flex flex-1 flex-col items-center gap-6">
                      
<div className="w-full h-96 relative">
  <PlasmaVisualizer />
</div>

                      <AnimatePresence mode="wait">
                        <motion.div
                          key={transcript.text || conversationState.label}
                          initial={{ opacity: 0, y: 6 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, y: -6 }}
                          className="min-h-[3.75rem] max-h-[4.5rem] overflow-hidden text-center"
                        >
                          <p className="text-xs uppercase tracking-[0.35em] text-slate-400">
                            {transcript.speaker === "user" ? "You" : "Assistant"}
                          </p>
                          <p className="mt-2 text-base font-medium text-slate-100 line-clamp-3">
                            {transcript.text || "Say hello to start the conversation."}
                          </p>
                        </motion.div>
                      </AnimatePresence>
                    </div>
                  </div>

                  <div className="relative max-h-32 overflow-hidden rounded-2xl border border-white/10 bg-white/[0.02] p-4">
                    <div className="absolute inset-0 bg-gradient-to-br from-white/5 via-transparent to-transparent" />
                    <div className="relative">
                      <TranscriptOverlay participant="remote" fadeInDuration={500} fadeOutDuration={1500} />
                    </div>
                  </div>

                  <div className="flex flex-col gap-4">
                    <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-4 shadow-inner">
                      <UserAudioControl size="md" />
                    </div>
                    <motion.button
                      whileHover={{ scale: 1.02, y: -2 }}
                      whileTap={{ scale: 0.98 }}
                      onClick={handleToggle}
                      className="flex items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-rose-500 via-red-500 to-amber-500 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-rose-900/40"
                    >
                      <PhoneOff size={18} />
                      End conversation
                    </motion.button>
                  </div>
                </div>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  );
};
