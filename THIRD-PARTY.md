# WebODM exporter attribution

webodm_export.py derives from WebODM app/splats.py at upstream revision
51c8f98b35de920d347631bcb99ed06180a6cafd, copyright WebODM contributors,
licensed under GNU AGPL version 3 or later. The complete license is included
in WEBODM-LICENSE.txt. Source: https://github.com/OpenDroneMap/WebODM

Adaptations remove Django dependencies and ZIP export, use explicit task assets
and RTC offsets, and reject invalid input/resize failures. Preserve this notice
and corresponding source when distributing the application package.
