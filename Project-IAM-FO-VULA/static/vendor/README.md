# Vendored browser libraries

These files are stored locally so the application can import KMZ and Excel files when public CDNs are unavailable.

- `jszip.min.js`: JSZip 3.10.1, originally loaded from cdnjs.
- `xlsx.full.min.js`: SheetJS Community Edition 0.18.5, originally loaded from jsDelivr.

When upgrading either library, test KML/KMZ imports, occupation spreadsheets, customer spreadsheets, and Excel exports before deployment.
