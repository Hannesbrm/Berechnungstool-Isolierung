from Isolierung_ui import run_ui


def main():
    try:
        run_ui()
    except Exception as e:
        import traceback
        print("FEHLER:")
        traceback.print_exc()
        input("\nDrücke Enter zum Schließen...")

if __name__ == '__main__':
    main()
