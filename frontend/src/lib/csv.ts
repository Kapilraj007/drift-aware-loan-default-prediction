export class FileParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FileParseError";
  }
}

function parseCsvLine(line: string): string[] {
  const cells: string[] = [];
  let cell = "";
  let quoted = false;

  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (character === '"') {
      if (quoted && line[index + 1] === '"') {
        cell += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (character === "," && !quoted) {
      cells.push(cell.trim());
      cell = "";
    } else {
      cell += character;
    }
  }
  if (quoted) {
    throw new FileParseError("The CSV contains an unmatched quote.");
  }
  cells.push(cell.trim());
  return cells;
}

export function parseDelimitedRows(text: string): Record<string, string>[] {
  const lines = text
    .replace(/^\uFEFF/, "")
    .split(/\r?\n/)
    .filter((line) => line.trim().length > 0);
  if (lines.length < 2) {
    throw new FileParseError("Provide a header row and at least one data row.");
  }
  const headers = parseCsvLine(lines[0]).map((header) => header.trim());
  if (headers.some((header) => !header)) {
    throw new FileParseError("Each CSV column needs a header.");
  }
  return lines.slice(1).map((line, rowIndex) => {
    const cells = parseCsvLine(line);
    if (cells.length !== headers.length) {
      throw new FileParseError(`Row ${rowIndex + 2} has ${cells.length} cells; expected ${headers.length}.`);
    }
    return Object.fromEntries(headers.map((header, index) => [header, cells[index]]));
  });
}

export async function parseApplicationFile(file: File): Promise<Record<string, unknown>> {
  const text = await file.text();
  if (file.name.toLowerCase().endsWith(".json")) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      throw new FileParseError("The JSON file is not valid.");
    }
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
      throw new FileParseError("Provide one application object in the JSON file.");
    }
    return parsed as Record<string, unknown>;
  }
  const [firstRow] = parseDelimitedRows(text);
  return firstRow;
}

export async function parseCohortFile(file: File): Promise<Record<string, unknown>[]> {
  const text = await file.text();
  if (file.name.toLowerCase().endsWith(".json")) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      throw new FileParseError("The JSON file is not valid.");
    }
    if (!Array.isArray(parsed) || parsed.some((row) => !row || typeof row !== "object" || Array.isArray(row))) {
      throw new FileParseError("Provide a JSON array of row objects for a cohort.");
    }
    return parsed as Record<string, unknown>[];
  }
  return parseDelimitedRows(text);
}
