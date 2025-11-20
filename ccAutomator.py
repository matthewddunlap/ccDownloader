import argparse
import re
import sys
from automator import CardConjurerAutomator

def parse_card_file(filepath):
    """
    Parses the input file to extract card names, ignoring the leading numbers.
    """
    card_names = []
    try:
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                # Use regex to ignore leading numbers and capture the rest of the line.
                match = re.match(r'^\d+\s+(.*)', line)
                if match:
                    card_names.append(match.group(1).strip())
    except FileNotFoundError:
        print(f"Error: Input file not found at '{filepath}'", file=sys.stderr)
        sys.exit(1)
    return card_names

def main():
    """
    Main entry point for the script. Parses arguments and orchestrates the automation.
    """
    parser = argparse.ArgumentParser(
        description="Automate card creation in Card Conjurer using Selenium.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        '--url',
        required=True,
        help="The URL for the Card Conjurer web app."
    )
    parser.add_argument(
        '--frame',
        required=True,
        help="The name of the frame to select from the dropdown (e.g., 'Seventh')."
    )
    parser.add_argument(
        'input_file',
        help="A plain text file with a list of card names to process and capture.\n"
             "Format: <number> <Card Name>\n"
             "Example:\n"
             "1 Hidden Necropolis\n"
             "1 Star Charter"
    )
    parser.add_argument(
        '--include-set',
        help="Whitelist of sets to capture, provided as a comma-separated list (e.g., 'DRK,LEG')."
    )
    parser.add_argument(
        '--exclude-set',
        help="Blacklist of sets to ignore, provided as a comma-separated list (e.g., 'LEA,LEB')."
    )
    parser.add_argument(
        '--set-selection',
        default='earliest',
        choices=['latest', 'earliest', 'random', 'all'],
        help="Determines the final capture logic after filtering:\n"
             "For '--card-selection cardconjurer':\n"
             "  'all': Capture every print that survives the filters.\n"
             "  'latest'/'earliest'/'random': Pick a representative print, then capture all prints from its set.\n"
             "For '--card-selection scryfall':\n"
             "  'all': Capture all unique art prints from Scryfall that survive filters.\n"
             "  'latest'/'earliest'/'random': Pick a single print (latest/earliest/random) matching unique Scryfall art.\n"
             "(defaults to 'earliest')"
    )
    parser.add_argument(
        '--card-selection',
        required=True,
        choices=['scryfall', 'cardconjurer'],
        help="Determines the source for card versions:\n"
             "'scryfall': Use the Scryfall API to determine unique art prints.\n"
             "'cardconjurer': Use the prints available directly from the Card Conjurer UI dropdown."
    )
    parser.add_argument(
        '--no-match-selection',
        default='earliest',
        choices=['skip', 'latest', 'earliest', 'random', 'all'],
        help="Defines the behavior when a Scryfall query (with or without filters) fails to find a match.\n"
             "'skip': Skip the card entirely.\n"
             "'latest'/'earliest'/'random'/'all': Apply this strategy to the available Card Conjurer prints as a fallback.\n"
             "(defaults to 'earliest')"
    )
    parser.add_argument(
        '--render-delay',
        type=float,
        default=1.5,
        help="Seconds to wait after selecting a print before capturing. (default: 1.5)"
    )
    parser.add_argument(
        '--prime-file',
        help="Optional: A plain text file with card names to prime the renderer before capture."
    )
    parser.add_argument(
        '--no-headless',
        action='store_true',
        help="Run the browser in non-headless mode for debugging purposes."
    )

    parser.add_argument(
        '--white-border',
        action='store_true',
        help="Apply the white border to the card frame."
    )

    # Power/Toughness Arguments
    parser.add_argument(
        '--pt-bold',
        action='store_true',
        help="Wrap the Power/Toughness text in {bold} tags."
    )

    parser.add_argument(
        '--pt-font-size',
        type=int,
        metavar='NUM',
        help="Add a {fontsize#} tag to the Power/Toughness text."
    )

    parser.add_argument(
        '--pt-kerning',
        type=int,
        metavar='NUM',
        help="Add a {kerning#} tag to the Power/Toughness text."
    )
    parser.add_argument(
        '--pt-shadow',
        type=int,
        metavar='NUM',
        help="Add a {shadow#} tag to the Power/Toughness text."
    )

    parser.add_argument(
        '--pt-up',
        type=int,
        metavar='NUM',
        help="Add a {up#} tag to the Power/Toughness text."
    )

    # Title Arguments
    parser.add_argument(
        '--title-font-size', type=int, metavar='NUM', help="Add a {fontsize#} tag to the Title text.")
    parser.add_argument(
        '--title-shadow', type=int, metavar='NUM', help="Add a {shadow#} tag to the Title text.")
    parser.add_argument(
        '--title-kerning', type=int, metavar='NUM', help="Add a {kerning#} tag to the Title text.")
    parser.add_argument(
        '--title-left', type=int, metavar='NUM', help="Add a {left#} tag to the Title text.")

    # Type Line Arguments
    parser.add_argument(
        '--type-font-size', type=int, metavar='NUM', help="Add a {fontsize#} tag to the Type text.")
    parser.add_argument(
        '--type-shadow', type=int, metavar='NUM', help="Add a {shadow#} tag to the Type text.")
    parser.add_argument(
        '--type-kerning', type=int, metavar='NUM', help="Add a {kerning#} tag to the Type text.")
    parser.add_argument(
        '--type-left', type=int, metavar='NUM', help="Add a {left#} tag to the Type text.")

    parser.add_argument(
        '--flavor-font',
        type=int,
        metavar='NUM',
        help="If rules text contains {flavor}, inserts a {fontsize#} tag immediately after it."
    )

    parser.add_argument(
        '--rules-down',
        type=int,
        metavar='NUM',
        help="Add a {down#} tag to the Rules text."
    )

    parser.add_argument(
        '--rules-bounds-y',
        type=int,
        metavar='NUM',
        help="Adjust the Y position of the rules text box by this amount."
    )

    parser.add_argument(
        '--rules-bounds-height',
        type=int,
        metavar='NUM',
        help="Adjust the height of the rules text box by this amount."
    )

    parser.add_argument(
        '--hide-reminder-text',
        action='store_true',
        help="Check the 'Hide reminder text' checkbox."
    )

    parser.add_argument(
        '--image-server',
        help="The base URL of the web server where custom art is stored (e.g., 'http://mtgproxy:4242')."
    )
    parser.add_argument(
        '--image-server-path',
        help="The path on the image server where the art files are located (e.g., '/local_art/upscaled/')."
    )
    parser.add_argument(
        '--art-path',
        default='/local_art/art/',
        help="The base path on the image server for art assets (default: '/local_art/art/')."
    )

    parser.add_argument(
        '--autofit-art',
        action='store_true',
        help="Check the 'Autofit when setting art' checkbox before applying custom art."
    )

    parser.add_argument(
        '--upscale-art',
        action='store_true',
        help="Enable Ilaria upscaling for custom art."
    )
    parser.add_argument(
        '--ilaria-url',
        help="The URL for the Ilaria upscaling service (e.g., 'https://matthewddunlap-ilaria.hf.space/')."
    )
    parser.add_argument(
        '--upscaler-model',
        default='RealESRGAN_x2plus',
        help="The specific model to use for Ilaria upscaling (default: 'RealESRGAN_x2plus')."
    )
    parser.add_argument(
        '--upscaler-factor',
        type=int,
        default=4,
        help="The factor by which to upscale the image (default: 4)."
    )

    # --- START OF MODIFIED ARGUMENTS ---
    # Create a mutually exclusive group for the output destination
    output_group = parser.add_mutually_exclusive_group(required=True)
    
    output_group.add_argument(
        '--output-dir',
        help="Directory to save the card images locally."
    )
    output_group.add_argument(
        '--upload-path',
        help="If specified, uploads the final PNG to this path on the --image-server (e.g., '/upload')."
    )
    
    parser.add_argument(
        '--upload-secret',
        help="Optional: A secret key sent in the 'X-Upload-Secret' header for authentication."
    )
    # --- END OF MODIFIED ARGUMENTS ---

    overwrite_group = parser.add_argument_group('Overwrite Options')
    overwrite_group.add_argument(
        '--overwrite',
        action='store_true',
        help="If a file with the same name exists on the server, overwrite it. Default is to skip."
    )
    overwrite_group.add_argument(
        '--overwrite-older-than',
        type=str,
        metavar='TIME',
        help="Overwrite if the server file is OLDER than the given timestamp (yyyy-mm-dd-hh-mm-ss) or relative time (e.g., 5m, 2h)."
    )
    overwrite_group.add_argument(
        '--overwrite-newer-than',
        type=str,
        metavar='TIME',
        help="Overwrite if the server file is NEWER than the given timestamp (yyyy-mm-dd-hh-mm-ss) or relative time (e.g., 5m, 2h)."
    )

    args = parser.parse_args()

    # --- Validation ---
    if args.overwrite_older_than and args.overwrite_newer_than:
        parser.error("Cannot use --overwrite-older-than and --overwrite-newer-than together.")

    if args.upload_path and not args.image_server:
        parser.error("--upload-path requires --image-server to be set.")

    if args.upload_secret and not args.upload_path:
        parser.error("--upload-secret is only valid when using --upload-path.")

    # Determine if we are in local save mode or upload mode
    save_locally = True if args.output_dir else False

    card_names_to_process = parse_card_file(args.input_file)
    if not card_names_to_process:
        print("No valid card names found in the input file to process. Exiting.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(card_names_to_process)} cards to process for capture.")

    try:
        with CardConjurerAutomator(
            url=args.url,
            # Pass the output directory, which might be None if uploading
            download_dir=args.output_dir,
            headless=not args.no_headless,
            include_sets=args.include_set,
            exclude_sets=args.exclude_set,
            card_selection_strategy=args.card_selection,
            set_selection_strategy=args.set_selection,
            no_match_selection=args.no_match_selection,
            render_delay=args.render_delay,
            white_border=args.white_border,
            pt_bold=args.pt_bold,
            pt_shadow=args.pt_shadow,
            pt_font_size=args.pt_font_size,
            pt_kerning=args.pt_kerning,
            pt_up=args.pt_up,
            title_font_size=args.title_font_size,
            title_shadow=args.title_shadow,
            title_kerning=args.title_kerning,
            title_left=args.title_left,
            type_font_size=args.type_font_size,
            type_shadow=args.type_shadow,
            type_kerning=args.type_kerning,
            type_left=args.type_left,
            flavor_font=args.flavor_font,
            rules_down=args.rules_down,
            rules_bounds_y=args.rules_bounds_y,
            rules_bounds_height=args.rules_bounds_height,
            hide_reminder_text=args.hide_reminder_text,
            image_server=args.image_server,
            image_server_path=args.image_server_path,
            art_path=args.art_path,
            autofit_art=args.autofit_art,
            upscale_art=args.upscale_art,
            ilaria_url=args.ilaria_url,
            upscaler_model=args.upscaler_model,
            upscaler_factor=args.upscaler_factor,
            upload_path=args.upload_path,
            upload_secret=args.upload_secret,
            overwrite=args.overwrite,
            overwrite_older_than=args.overwrite_older_than,
            overwrite_newer_than=args.overwrite_newer_than
        ) as automator:
            
            automator.set_frame(args.frame)

            if args.prime_file:
                prime_card_names = parse_card_file(args.prime_file)
                if prime_card_names:
                    print(f"\n--- Starting Renderer Priming with {len(prime_card_names)} cards ---")
                    for i, card_name in enumerate(prime_card_names, 1):
                        print(f"Priming card {i}/{len(prime_card_names)}: '{card_name}'")
                        automator.process_and_capture_card(card_name, is_priming=True)
                    print("--- Renderer Priming Complete ---")
                else:
                    print(f"Warning: Prime file '{args.prime_file}' was provided but contained no valid card names.", file=sys.stderr)

            print("\n--- Starting Main Card Processing ---")
            for i, card_name in enumerate(card_names_to_process, 1):
                print(f"--- Processing card {i}/{len(card_names_to_process)} ---")
                automator.process_and_capture_card(card_name)

    except Exception as e:
        print(f"\nA critical error occurred during automation: {e}", file=sys.stderr)
        sys.exit(1)

    print("\nAutomation complete.")

if __name__ == "__main__":
    main()
