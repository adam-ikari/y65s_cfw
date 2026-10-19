kb_dir = meson.current_source_dir()

keyboards += {
    'yd-y65s' : {
        'dir' : kb_dir,
        'platform' : 'sh68f90',
        'src' : files(
            'user_matrix.c',
            'user_init.c',
            'user_sleep.c',
            'kb.c',
        ),
        'layouts' : {
            'default' : {
                'dir' : kb_dir / 'layouts/default',
                'src' : files('layouts/default/layout.c'),
            },
        },
        # Per-key RGB and the wireless module have not been decoded yet.  The
        # board is USB-only for now; SMK's defaults give it a distinct identity
        # (258a:dead) so it cannot be confused with the factory firmware.
        'options' : {},
    },
}
