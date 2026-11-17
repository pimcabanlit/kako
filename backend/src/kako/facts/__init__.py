"""The fact rules: the attribute catalog, snapshots and the validation rules (V-01 to V-08, V-16).

Pure: nothing here imports the database, Meko or a model SDK (a test enforces it). The writes
(replace, retract) live in kako.db.fact_store, which applies these rules inside a transaction.
"""
