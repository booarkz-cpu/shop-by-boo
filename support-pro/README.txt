Support Pro settings of an installed server: the installer writes support-pro/.env here (secrets, never in git).
The code of Support Pro lives in services/support-pro/. The path of the .env file did not change with the folder
layout, so an installed server keeps its settings through updates.
