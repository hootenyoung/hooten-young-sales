"""xlsx parsers. Broker-format-specific.

Each parser converts a raw xlsx file into a stable canonical model.
The services layer is responsible for writing those canonical objects
to the database. If the broker changes the file format, only the
parser swaps — schemas, services, and API layers are untouched.
"""
