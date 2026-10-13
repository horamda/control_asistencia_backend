"""Preserve user text as data in spreadsheet downloads."""
import csv


def spreadsheet_text(value):
    if isinstance(value, str) and value.lstrip(' \t\r\n').startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


class SafeCsvWriter:
    def __init__(self, stream, **kwargs):
        self.writer = csv.writer(stream, **kwargs)

    def writerow(self, row):
        return self.writer.writerow([spreadsheet_text(value) for value in row])

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)


def text_only_workbook(workbook):
    """Data-only exports do not contain intentional Excel formulas."""
    for sheet in workbook.worksheets:
        for row in sheet:
            for cell in row:
                if cell.data_type == 'f':
                    cell.data_type = 's'
