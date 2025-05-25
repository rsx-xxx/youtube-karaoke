from pathlib import Path
import sys

# Constant for names to exclude.
EXCLUDED_NAMES = {"venv",
                  "__pycache__",
                  "structure.py",
                  "output.txt",
                  "downloads",
                  "processed",
                  ".old"}


def generate_tree_lines(directory: Path, prefix: str = '', is_last: bool = True) -> (list, list):
    """
    Recursively generates the tree structure lines and collects file paths.

    Args:
        directory (Path): The current directory or file.
        prefix (str): Prefix for indentation.
        is_last (bool): Flag indicating if the current item is the last in its level.

    Returns:
        tuple: (lines, files) where lines is a list of strings representing the tree,
               and files is a list of file paths in the same order.
    """
    lines = []
    files = []
    connector = "└── " if is_last else "├── "
    lines.append(prefix + connector + directory.name)

    if directory.is_file():
        files.append(directory)
        return lines, files

    # For directories: sort children and filter out hidden items and excluded names.
    children = sorted(
        [child for child in directory.iterdir() if not child.name.startswith('.') and child.name not in EXCLUDED_NAMES],
        key=lambda x: x.name
    )
    count = len(children)
    for idx, child in enumerate(children):
        is_last_child = (idx == count - 1)
        new_prefix = prefix + ("    " if is_last else "│   ")
        child_lines, child_files = generate_tree_lines(child, new_prefix, is_last_child)
        lines.extend(child_lines)
        files.extend(child_files)
    return lines, files


def main(root_path: str, output_file: str):
    root = Path(root_path)
    if not root.exists():
        print(f"Error: {root} does not exist.")
        sys.exit(1)

    # For the root directory: filter out hidden items and excluded names.
    tree_lines = [root.name]
    all_files = []
    children = sorted(
        [child for child in root.iterdir() if not child.name.startswith('.') and child.name not in EXCLUDED_NAMES],
        key=lambda x: x.name
    )
    count = len(children)
    for idx, child in enumerate(children):
        is_last_child = (idx == count - 1)
        child_lines, child_files = generate_tree_lines(child, '', is_last_child)
        tree_lines.extend(child_lines)
        all_files.extend(child_files)

    with open(output_file, 'w', encoding='utf-8') as out:
        # Write directory structure.
        out.write("Directory Structure:\n")
        out.write("\n".join(tree_lines))
        out.write("\n\nFile Contents:\n")

        # Write contents of files.
        for file_path in all_files:
            out.write("\n" + "─" * 40 + "\n")
            out.write(f"File: {file_path}\n")
            out.write("─" * 40 + "\n")
            try:
                content = file_path.read_text(encoding='utf-8')
            except Exception as e:
                content = f"Could not read file: {e}"
            out.write(content)
            out.write("\n")

    print(f"Output successfully written to {output_file}")


if __name__ == '__main__':
    # Usage: python script.py [root_directory] [output_file]
    # Defaults: current directory and 'output.txt'
    root_directory = sys.argv[1] if len(sys.argv) > 1 else "."
    output_filename = sys.argv[2] if len(sys.argv) > 2 else "output.txt"
    main(root_directory, output_filename)
