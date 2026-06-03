import sys
import os

# Add agent_backend to sys.path
sys.path.append(os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from agent_backend.windows_only.uia_layer import WindowsUIALayer
    layer = WindowsUIALayer()
    print(f"Is available: {layer.is_available()}")
    
    if layer.is_available():
        # Test getting desktop windows
        windows = layer.get_desktop_windows()
        print(f"SUCCESS: Enumerated {len(windows)} desktop windows.")
        for w in windows[:5]:
            print(f"  - {w['process_name']}: {w['title']}")
    else:
        print("FAILED: UIA layer is not available")
except Exception as e:
    import traceback
    print("FAILED with exception:")
    traceback.print_exc()
