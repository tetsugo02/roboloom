# Rakuda-2 kinematic model

`assembly_2.urdf` is copied unchanged from robopy commit `cdfc94b`
(`src/robopy/models/rakuda/assembly_2/urdf/assembly_2.urdf`, the CAD export).
roboloom reads only its joint tree, origins and axes. The masses in the file
are CAD estimates and are not used; gravity models are identified on the robot
(`roboloom identify-gravity`). Meshes are not needed and not copied.
