import { create } from 'zustand';

export interface Message {
  role: 'user' | 'assistant';
  content: string;
}

interface ChatState {
  messages: Message[];
  isThinking: boolean;
  sendMessage: (content: string) => void;
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  isThinking: false,
  sendMessage: (content: string) => {
    // Add user message and set thinking state
    set((state) => ({
      messages: [...state.messages, { role: 'user', content }],
      isThinking: true,
    }));

    // Simulate agent response
    setTimeout(() => {
      set((state) => {
        let reply = "I am a local AI assistant. I can see your screen, run files, and execute terminal commands.";
        if (content.toLowerCase().includes('hello') || content.toLowerCase().includes('hi')) {
          reply = "Hello! I am Oryonix, your desktop AI agent. How can I assist you today?";
        } else if (content.toLowerCase().includes('chrome') || content.toLowerCase().includes('browser')) {
          reply = "Understood. I will prepare a plan to open Google Chrome and perform the requested search.";
        } else if (content.toLowerCase().includes('help')) {
          reply = "You can ask me to open programs, edit code files, manage projects, or help write code. Just let me know what you need!";
        }
        return {
          messages: [...state.messages, { role: 'assistant', content: reply }],
          isThinking: false,
        };
      });
    }, 1500);
  },
}));
