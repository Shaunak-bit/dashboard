import os
import sys

def main():
    # Find the dashboard script
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    script_path = os.path.join(base_path, 'realtime_wrench_bokeh.py')
    
    print("=" * 60)
    print("  Visual Wrench Guided Robot Navigation Dashboard")
    print("=" * 60)
    print("Starting server at http://localhost:5006")
    print("Opening browser...")
    print("Press Ctrl+C to stop\n")
    
    # Run Bokeh server programmatically
    from bokeh.server.server import Server
    from bokeh.application import Application
    from bokeh.application.handlers.script import ScriptHandler
    import webbrowser
    
    try:
        # Create Bokeh application from script
        handler = ScriptHandler(filename=script_path)
        app = Application(handler)
        
        # Create and start server
        server = Server({'/': app}, port=5006, allow_websocket_origin=["localhost:5006"])
        server.start()
        
        # Open browser
        webbrowser.open('http://localhost:5006/')
        
        print("Dashboard is running!")
        print("Press Ctrl+C to stop\n")
        
        # Keep server running
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