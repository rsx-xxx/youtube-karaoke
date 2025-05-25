"""
Marks “backend” as a proper Python package.

If you prefer to keep running the app via
    uvicorn app:app
inside the *backend* folder, this file is optional.

If you run the server from the **project root**:

    uvicorn backend.app:app --reload

the package marker is mandatory.
"""