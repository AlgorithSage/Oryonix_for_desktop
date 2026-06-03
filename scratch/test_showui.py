import sys
from pathlib import Path
import os
import torch

# Add agent_backend to path
_BACKEND_PATH = Path(__file__).parent.parent / "agent_backend"
if str(_BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(_BACKEND_PATH))

print("Python version:", sys.version)
print("PyTorch version:", torch.__version__)
print("CUDA Available:", torch.cuda.is_available())

try:
    from llm.showui_agent import ShowUIAgent
    print("ShowUIAgent class imported successfully!")
    
    # Attempt to instantiate and check imports
    agent = ShowUIAgent("showlab/ShowUI-2B")
    print("ShowUIAgent instantiated.")
    
    # Attempt to force model weight loading (NF4 quantized)
    print("Attempting to load weights into VRAM...")
    agent._ensure_loaded()
    print("SUCCESS: ShowUI-2B successfully loaded into VRAM on device:", agent._device)
except Exception as e:
    import traceback
    print("\nERROR loading ShowUI-2B model:")
    traceback.print_exc()
