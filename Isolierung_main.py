from Isolierung_ui import run_ui
from Isolierung_logic import compute_multilayer

def main():
    try:
        run_ui(calculate_callback=compute_multilayer)
    except Exception as e:
        import traceback
        print("FEHLER:")
        traceback.print_exc()
        input("\nDrücke Enter zum Schließen...")

if __name__ == '__main__':
    main()
