import os
import sys

# 🔥 FORCE LOAD BOKEH (CRITICAL)
import bokeh
import bokeh.plotting
import bokeh.models
import bokeh.server.server
import bokeh.application
import bokeh.application.handlers.script
import bokeh.document
import bokeh.layouts
import bokeh.embed


def main():
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))

    # 🔥 ADD THIS LINE (FINAL FIX)
    sys.path.insert(0, base_path)
    
    script_path = os.path.join(base_path, 'realtime_wrench_bokeh.py')
    
    print("=" * 60)
    print("  Visual Wrench Guided Robot Navigation Dashboard")
    print("=" * 60)
    print("Starting server at http://localhost:5006")
    print("Opening browser...")
    print("Press Ctrl+C to stop\n")
    
    from bokeh.server.server import Server
    from bokeh.application import Application
    from bokeh.application.handlers.script import ScriptHandler
    import webbrowser
    
    try:
        handler = ScriptHandler(filename=script_path, argv=[])
        app = Application(handler)
        
        server = Server({'/': app}, port=5006, allow_websocket_origin=["localhost:5006"])
        server.start()
        
        webbrowser.open('http://localhost:5006/')
        
        print("Dashboard is running!")
        print("Press Ctrl+C to stop\n")
        
        server.io_loop.start()
        
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
        server.stop()
        print("Dashboard stopped.")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...")


if __name__ == '__main__':
    main()